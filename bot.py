import slack
from flask import Flask, request, make_response
from slackeventsapi import SlackEventAdapter
import json
import requests
import collections
import random
from datetime import datetime


"""
NOTE: Every time NGROK is set up, you will have to update the Event Subscriptions, Slash Commands and Interactivity & Shortcuts sections
with the new host URL
"""

token_ = "<token here>"
signing_secret_ = "<signing secret here>"
client_secret_ = "<client secret here>"

message_reactions = {}

events = []

class Event:
    def __init__(self, users, channel_id, message_ts, event_date):
        self.users = users
        self.channel_id = channel_id
        self.message_ts = message_ts
        self.event_date = event_date


app = Flask(__name__)

client = slack.WebClient(token=token_)

slack_events_adapter = SlackEventAdapter(signing_secret_, "/slack/events", app)

user_queue = collections.deque() #IMPORTANT DATA STRUCTURE

conversations = {}


def get_channel_id(channel_name):
    channels_response = client.conversations_list()

    if channels_response["ok"]:
        channels = channels_response["channels"]

        for channel in channels:
            if channel["name"] == channel_name:
                return channel["id"]

    return None


def get_bot_user_id():
    response = client.auth_test()
    if response["ok"]:
        return response["user_id"]
    else:
        print("Error getting bot user ID:", response["error"])
        return None


bot_user_id = get_bot_user_id()


def refresh_queue():
    try:
        # Get the bot's own ID
        bot_id = client.auth_test()["user_id"]

        result = client.conversations_members(channel=get_channel_id("general"))
        if result["ok"]:
            members = result["members"]

            # Remove the bot's ID from the members list
            members = [member for member in members if member != bot_id]

            random.shuffle(members)
            user_queue.extend(members)
        else:
            print("Failed to fetch channel members:", result["error"])
    except Exception as e:
        print("Error refreshing user queue:", e)


def create_channel(users):
    try:
        result = client.conversations_create(name="picnic", is_private=True)
        if result["ok"]:
            channel = result["channel"]["id"]
            for user in users:
                client.conversations_invite(channel=channel, users=[user])
            return channel
        else:
            print("Failed to create channel:", result["error"])
            return None
    except Exception as e:
        print("Error creating channel:", e)
        return None

def get_queue():
    result = ""
    result += " CURRENT QUEUE (FRONT OF QUEUE IS AT BOTTOM): \n"
    for user in user_queue:
        result += f"<@{user}>\n"
    return result


# head of queue is on the right, tail on the left
# add to the queue: appendLeft, pop from queue: pop()

@app.route("/chill-shuffle", methods=["POST"])
def chill_shuffle():
    refresh_queue()
    return make_response(get_queue(), 200)


@app.route("/chill-queue", methods=["POST"])
def chill_queue():
    result = get_queue()
    # client.chat_postMessage(
    #     channel=get_channel_id("general"),
    #     text=result,
    # )
    return make_response(result, 200)

@app.route("/chill-create", methods=["POST"])
def chill_create():
    date_text = request.form['text']
    
    try:
        event_date = datetime.strptime(date_text, "%Y-%m-%d") # eg: 2023-08-11
    except ValueError:
        return make_response("Invalid date format. Please use YYYY-MM-DD.", 200)

    if event_date < datetime.now():
        return make_response("Invalid date. Please use a future date.", 200)

    if message_reactions or events:
        client.chat_postMessage(
            channel=get_channel_id("general"),
            text="There is already a picnic event in progress!",
        )
        return make_response("Picnic event already exists!", 200)
    if not user_queue or len(user_queue) < 4:
        refresh_queue()
        if len(user_queue) < 4:
            print("Not enough users for a picnic!")
            return make_response("", 200)

    users = [user_queue.pop() for i in range(4)]

    response = client.chat_postMessage(
        channel=get_channel_id("general"), #format string to include date
        text=f"*This week's picnic planners have been selected for {event_date.strftime('%B %d, %Y')}!* Participants, please check the thread below!",
    )

    if response["ok"]:
        thread_ts = response["message"]["ts"]
        response2 = client.chat_postMessage(
            channel=get_channel_id("general"),
            text=f"<@{users[0]}>, <@{users[1]}>, <@{users[2]}>, <@{users[3]}>! You have been chosen to plan this month's picnic event! Please RSVP using the reactions below ASAP!",
            thread_ts=thread_ts,
        )

        if response2["ok"]:
            message_ts = response2["message"]["ts"]
            channel_id = get_channel_id("general")
            message_reactions[(channel_id, message_ts)] = [collections.Counter(), users, [], event_date]

            try:
                # Add a checkmark reaction
                client.reactions_add(
                    channel=channel_id,
                    timestamp=message_ts,
                    name="white_check_mark",
                )

                # Add an X reaction
                client.reactions_add(
                    channel=channel_id,
                    timestamp=message_ts,
                    name="x",
                )
            except:
                print("Error adding reaction")

    return make_response("Picnic channel created and message posted", 200)


# Event listener
@slack_events_adapter.on("reaction_added")
def handle_reaction(event_data):
    event = event_data["event"]

    channel_id = event["item"]["channel"]
    message_ts = event["item"]["ts"]
    user = event["user"]
    reaction = event["reaction"]

    # Check if this is a message we're tracking reactions for
    if (channel_id, message_ts) in message_reactions and user != bot_user_id:
        if reaction == "x":
            if user in message_reactions[(channel_id, message_ts)][1]:
                if not user_queue:
                    client.chat_postMessage(
                        channel=channel_id,
                        text=f"User <@{user}> declined the invitation, but there are no more users in the queue, so the event will continue to stay pending.",
                        thread_ts=message_ts,
                    )
                else:
                    client.chat_postMessage(
                    channel=channel_id,
                    text=f"User <@{user}> declined the invitation.",
                    thread_ts=message_ts,
                    )
                    message_reactions[(channel_id, message_ts)][1].remove(user)
                    new_user = user_queue.pop()
                    message_reactions[(channel_id, message_ts)][1].append(new_user)
                    message_reactions[(channel_id, message_ts)][2].append(user)
                    client.chat_postMessage(
                        channel=channel_id,
                        text=f"User <@{new_user}> has been added to the event.",
                        thread_ts=message_ts,
                    )
            else:
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"User <@{user}> is not a participant in the event, so the event will continue to stay pending.",
                    thread_ts=message_ts,
                )
        elif reaction == "white_check_mark":
            message_reactions[(channel_id, message_ts)][0]["white_check_mark"] += 1
            print(message_reactions[(channel_id, message_ts)][0]["white_check_mark"])

            if message_reactions[(channel_id, message_ts)][0]["white_check_mark"] >= 1:
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"The picnic event has been confirmed for {message_reactions[(channel_id, message_ts)][3].strftime('%B %d, %Y')}! Thanks for your RSVP.",
                    thread_ts=message_ts,
                )
                events.append(Event(message_reactions[(channel_id, message_ts)][1], channel_id, message_ts, message_reactions[(channel_id, message_ts)][3]))
                print(events[0].event_date)
                for user in message_reactions[(channel_id, message_ts)][1]:
                    user_queue.appendleft(user)
                for user in message_reactions[(channel_id, message_ts)][2]:
                    user_queue.append(user)
                del message_reactions[(channel_id, message_ts)]
                


@slack_events_adapter.on("reaction_removed")
def reaction_removed(event_data):
    event = event_data["event"]
    message_ts = event["item"]["ts"]
    channel_id = event["item"]["channel"]


    if (channel_id, message_ts) in message_reactions:
        message_reactions[(channel_id, message_ts)][event["reaction"]][0] -= 1
        print(message_reactions[(channel_id, message_ts)][event["reaction"]])


@slack_events_adapter.on("message")
def handle_message(event_data):
    message = event_data["event"]

    if message.get("bot_id"):
        return

    user = message.get("user")
    text = message.get("text")

    if user in conversations:
        if text.lower() == "blue":
            client.chat_postMessage(
                channel=message["channel"], text="Blue is a great color!"
            )
        elif text.lower() == "red":
            client.chat_postMessage(
                channel=message["channel"], text="Red is a great color!"
            )
        else:
            client.chat_postMessage(channel=message["channel"], text="That's nice!")
        del conversations[user]
    elif text == "hi":
        channel = message["channel"]
        response = f"Hello <@{user}>! :tada:"
        client.chat_postMessage(channel=channel, text=response)
    elif text == "color":
        client.chat_postMessage(
            channel=message["channel"], text="What's your favorite color? Red or blue?"
        )
        conversations[user] = True

    return make_response("Message received", 200)


@app.route("/chill-edit", methods=["POST"])
def chill_edit():
    data = request.form
    trigger_id = data.get("trigger_id")

    api_url = "https://slack.com/api/dialog.open"

    dialog = {
        "title": "Chill-Create Dashboard",
        "callback_id": "fav_color",
        "submit_label": "Submit",
        "elements": [
            {
                "label": "Select your character",
                "type": "select",
                "name": "character",
                "option_groups": [
                    {
                        "label": "Characters",
                        "options": [
                            {"label": "Maru", "value": "maru"},
                            {"label": "Lil Bub", "value": "lilbub"},
                            {"label": "Hamilton the Hipster Cat", "value": "hamilton"},
                        ],
                    }
                ],
            },
            {
                "label": "What's your favorite color?",
                "name": "color",
                "type": "text",
                "hint": "e.g., blue or green",
            },
        ],
    }

    api_data = {"token": token_, "trigger_id": trigger_id, "dialog": json.dumps(dialog)}

    res = requests.post(api_url, data=api_data)

    return make_response()


@app.route("/interactive", methods=["POST"])
def interactive():
    try:
        payload = json.loads(request.form.get("payload"))
        print(f"Received payload: {payload}")  # Log the received payload

        if payload["type"] == "dialog_submission":
            user = payload["user"]["id"]
            responses = payload["submission"]

            color = responses["color"]
            character = responses["character"]

            client.chat_postMessage(
                channel=user,
                text=f"Your favorite color is {color} and your favorite character is {character}!",
            )
            print("Message sent successfully")  # Log a successful message send
        return make_response("", 200)
    except Exception as e:
        print(f"Exception occurred: {e}")  # Log any exceptions that occur
        return make_response("", 500)  # Return a 500 status code if an exception occurs


def interactive2():
    return make_response("", 200)


if __name__ == "__main__":
    app.run(debug=True)