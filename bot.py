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

exclude = []

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
    user_queue.clear()
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

            for user in exclude:
                user_queue.remove(user)
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

def find_user_by_handle(handle):
    handle_to_find = handle.lstrip('@')
    result = client.users_list()
    if result["ok"]:
        users = result["members"]
        for user in users:
            if user["name"] == handle_to_find:
                return user["id"]
    return None
    


# head of queue is on the right, tail on the left
# add to the queue: appendLeft, pop from queue: pop()
@app.route("/chill-help", methods=["POST"])
def chill_help():
    result = ""
    result += " *COMMANDS:* \n"
    result += " /chill-create: Creates a picnic event. \n"
    result += " /chill-delete: Deletes a picnic event. \n"
    result += " /chill-queue: Displays the current queue. \n"
    result += " /chill-shuffle: Shuffles the queue. \n"
    result += " /chill-edit: Edits the queue.  Written as Swap, Include or Exclude followed by user handles.\n"
    result += " /chill-event: Displays the current picnic event. \n"
    result += " /chill-excluded: Displays the current excluded users. \n"
    return make_response(result, 200)

@app.route("/chill-excluded", methods=["POST"])
def chill_excluded():
    result = ""
    result += " EXCLUDED USERS: \n"
    for user in exclude:
        result += f"<@{user}>\n"
    return make_response(result, 200)

@app.route("/chill-event", methods=["POST"])
def chill_event():
    if not events:
        return make_response("There is no picnic event in progress!", 200)
    if events[0].event_date < datetime.now():
        return make_response("The picnic event has already passed!", 200)
    if events[0].event_date > datetime.now():
        return make_response(f"The picnic event is scheduled for {events[0].event_date.strftime('%B %d, %Y')}.\n Planners have been chosen to be {' '.join([f'<@{user}>' for user in events[0].users])}.", 200)
    

@app.route("/chill-edit", methods=["POST"]) # ARSG: TYPE (SWAP OR EXCLUDE), + either (USER_ID1 USERID2) or (USER_ID)
def edit_chill():
    text = request.form['text']
    arg1, arg2, arg3 = (text.split() + [None, None, None])[:3]

    if not arg1:
        return make_response("Please enter a valid command.", 200)

    if(arg1.lower() == "swap"):
        if(not arg2 or not arg3):
            return make_response("Please enter two user handles to swap.", 200)
        if(arg2 == arg3):
            return make_response("Please enter two different user handles to swap.", 200)
        
        arg2_id = find_user_by_handle(arg2)
        arg3_id = find_user_by_handle(arg3)

        if(not arg2_id or not arg3_id):
            return make_response("Please enter valid user handles.", 200)
        if(arg2_id not in user_queue and arg3_id not in user_queue):
            return make_response("Please enter user handles that are in the queue.", 200)
        
        current_list = events[0].users

        if(arg2_id not in current_list and arg3_id not in current_list):
            return make_response("Please enter user handles that are in the event.", 200)
        if(arg2_id in current_list):
            current_list[current_list.index(arg2_id)] = arg3_id
            user_queue.remove(arg3_id)
            user_queue.appendleft(arg2_id)
        else:
            current_list[current_list.index(arg3_id)] = arg2_id
            user_queue.remove(arg2_id)
            user_queue.appendleft(arg3_id)

        return make_response(f"<@{arg2_id}> and <@{arg3_id}> have been swapped.", 200)

    if(arg1.lower() == "exclude"):

        arg2_id = find_user_by_handle(arg2)

        if not arg2_id in user_queue:
            return make_response("Please enter a user handle that is in the queue.", 200)
        if arg2_id in exclude:
            return make_response("User is already excluded.", 200)
        if events and arg2_id in events[0].users:
            return make_response("User is already in the event.", 200)
        exclude.append(arg2_id)
        user_queue.remove(arg2_id)
        return make_response(f"{arg2} has been excluded.", 200)
    
    if(arg1.lower() == "include"):

        arg2_id = find_user_by_handle(arg2)

        if not arg2_id in exclude:
            return make_response("Please enter a user handle that is excluded.", 200)
        exclude.remove(arg2_id)
        user_queue.appendleft(arg2_id)
        return make_response(f"{arg2} has been included.", 200)

    return make_response("Please enter a valid command.", 200)

@app.route("/chill-shuffle", methods=["POST"])
def chill_shuffle():
    refresh_queue()
    return make_response(get_queue(), 200)


@app.route("/chill-queue", methods=["POST"])
def chill_queue():
    result = get_queue()
    return make_response(result, 200)

@app.route("/chill-delete", methods=["POST"])
def chill_delete():
    if not events:
        return make_response("There is no picnic event in progress!", 200)
    
    client.chat_postMessage(
        channel=events[0].channel_id,
        text=f"The picnic event has been cancelled.\n Deleted Event: {events[0].event_date.strftime('%B %d, %Y')}.\n Planners were {' '.join([f'<@{user}>' for user in events[0].users])}."
    )
    for user in events[0].users:
        user_queue.appendleft(user)
    del events[0]
    return make_response("Picnic event has been cancelled.", 200)

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
            return make_response("Not enough users for a picnic!", 200)

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


"""
NOTE: These are the formats you should follow when creating a dialogue box for chill-edit

"elements": [
            {
                "label": "What's your favorite color?",
                "name": "color",
                "type": "text",
                "hint": "e.g., blue or green"
            }
        ]




"elements": [
            {
                "label": "Select your character",
                "type": "select",
                "name": "color_selection",
                "option_groups": [
                    {
                        "label": "Characters",
                        "options": [
                            {
                                "label": "Maru",
                                "value": "maru"
                            },
                            {
                                "label": "Lil Bub",
                                "value": "lilbub"
                            },
                            {
                                "label": "Hamilton the Hipster Cat",
                                "value": "hamilton"
                            }
                        ]
                    }
                ]
            },
            {
                "label": "What's your favorite color?",
                "name": "color",
                "type": "text",
                "hint": "e.g., blue or green"
            }
        ]
    }
"""
