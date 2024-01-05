import firebase_admin
from firebase_admin import auth, credentials, firestore, initialize_app
from flask import Flask, Blueprint, request, jsonify, render_template, redirect, url_for, Response
from flask_cors import CORS
import json
import pyrebase
from datetime import datetime
import os
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Pause
import urllib.parse
import random

app = Flask(__name__)
CORS(app,resources={r"/*":{"origins":"*"}})

cred = credentials.Certificate("i-sole-111bc-firebase-adminsdk-f1xl8-c99396fd2b.json")
firebase_admin.initialize_app(cred)
account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

db=firestore.client()
client = Client(account_sid, auth_token)

@app.route('/initialize_counter', methods=['POST'])
def initialize_counter():
    data = request.json
    username = data['username']
    initialize_user_thread_counter(username)
    return jsonify({"success": True})

@app.route('/signup', methods=['POST'])
def signup():
    try:
        # Parse the incoming data from the signup form
        signup_data = request.json
        username = signup_data['username']
        email = signup_data['email']
        full_name = signup_data['fullName']
        role = signup_data['role']
        password = signup_data['password']  # Be careful with handling passwords
        patient_id = signup_data.get('patientID', None)  # Optional field

         # Check if the role is 'Patient' and generate a unique patientID
        if role == 'Patient':
            patient_id = generate_unique_patient_id()
            update_id_map(patient_id, username)

        # Create a reference to the Firestore document
        user_ref = db.collection('users').document(username)

        # Create a new document with the provided data
        user_ref.set({
            'email': email,
            'fullName': full_name,
            'role': role,
            'password': password,  # Consider hashing the password
            'patientID': patient_id
        })

        return jsonify({"success": True, "message": "User created successfully", 'patientID': patient_id}), 201

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/get_username_by_patient_id/<patient_id>', methods=['GET'])
def get_username_by_patient_id(patient_id):
    try:
        # Retrieve the username mapped to the patient_id
        username = get_username_from_patient_id(patient_id)
        if username:
            return jsonify({"success": True, "username": username}), 200
        else:
            return jsonify({"success": False, "message": "Username not found for the given patient ID"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/start_new_thread', methods=['POST'])
def start_thread():
    data = request.json
    username = data['username']
    sender = data['sender']
    message = data['message']
    start_new_thread_with_message(username, message, sender)
    return jsonify({"success": True})

@app.route('/add_message', methods=['POST'])
def add_message():
    data = request.json
    username = data['username']
    index = data['index']
    message = data['message']
    add_message_to_conversation(username, index, message)
    return jsonify({"success": True})

@app.route('/get_all_conversations/<username>', methods=['GET'])
def get_all(username):
    conversations = get_all_conversations(username)
    return jsonify(conversations)

@app.route('/get_one_conversation/<username>/<int:index>', methods=['GET'])
def get_one(username, index):
    conversation = get_one_conversation(username, index)
    if conversation is not None:
        return jsonify(conversation)
    else:
        return jsonify({"error": "Conversation not found"}), 404


@app.route('/add_contact', methods=['POST'])
def add_contact():
    try:
        # Parse the request data
        data = request.get_json()
        username = data['username']  # Make sure to send 'username' in your request payload
        new_contact = data['newContact']
        contact_info = {
            'name': new_contact['contactName'],
            'relationship': new_contact['relationship'],
            'phone_number': new_contact['phoneNumber'],
            'email': new_contact.get('email', None),  # Optional field
            'glucose_level_alert': new_contact['glucoseAlert'],
            'medication_reminder': new_contact['medicationReminder']
        }
        
        # Add a new contact document to the 'contacts' subcollection
        contact_ref = db.collection('users').document(username).collection('contacts').document()
        contact_ref.set(contact_info)
        
        # Return success response
        return jsonify({"success": True}), 200
    
    except Exception as e:
        app.logger.error(f"An error occurred: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/delete_contact', methods=['POST'])
def delete_contact():
    try:
        # Parse the request data
        data = request.get_json()
        username = data['username']  # Username to identify the user's document
        contact_name = data['contactName']  # Contact name to identify the contact document

        # Query the contacts subcollection for the user to find the contact document
        contacts_ref = db.collection('users').document(username).collection('contacts')
        contacts = contacts_ref.where('name', '==', contact_name).stream()

        # Delete the contact document(s)
        for contact in contacts:
            contact_ref = contacts_ref.document(contact.id)
            contact_ref.delete()

        # Return success response
        return jsonify({"success": True, "message": "Contact deleted successfully"}), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"An error occurred: {e}"}), 500

@app.route('/get_all_contacts/<username>', methods=['GET'])
def get_all_contacts(username):
    try:
        # Query the contacts subcollection for the given user
        contacts_ref = db.collection('users').document(username).collection('contacts')
        contacts_query = contacts_ref.stream()

        # Collect contact data from the documents
        contacts = []
        for contact_doc in contacts_query:
            contact_info = contact_doc.to_dict()
            contact_info['id'] = contact_doc.id  # Optionally include the document ID
            contacts.append(contact_info)

        # Return the contacts in the response
        return jsonify({"success": True, "contacts": contacts}), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"An error occurred: {e}"}), 500


@app.route("/make_call", methods=['GET', 'POST'])
def make_call():
    # Get the 'to' phone number and the message from URL parameters
    if request.method == 'POST':
        data = request.json
        to_number = data.get('to')
        message = data.get('message', 'This is a default message')
    else:
        to_number = request.values.get('to')
        encoded_message = request.values.get('message', 'This is a default message')
        message = urllib.parse.unquote(encoded_message)

    print('Hello World')

    # Create a callback URL for the voice response
    callback_url = request.url_root + "voice?message=" + urllib.parse.quote(message)

    # Make the call using Twilio client
    try:
        call = client.calls.create(
            to=to_number,
            from_="+18254351557",
            url=callback_url,
            record=True
        )
        return f"Call initiated. SID: {call.sid}"
    except Exception as e:
        return f"Error: {e}"

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    # Get the message from the URL parameter
    message = request.values.get('message', 'This is a default message')
    
    # Create a VoiceResponse object
    response = VoiceResponse()

    # Split the message by lines and process each line
    for line in message.split('\n'):
        response.say(line, voice='Polly.Joanna-Neural', language='en-US')
        if line.strip().endswith('?'):
            response.append(Pause(length=3))

    # Return the TwiML as a string
    return Response(str(response), mimetype='text/xml')


def initialize_user_thread_counter(username): # need to call at creation of each account
    # Reference to the user's thread counter document
    counter_ref = db.collection('users').document(username).collection('feedback').document('thread_counter')
    
    # Set the initial value of the counter
    counter_ref.set({'last_thread_number': 0})


def generate_unique_patient_id():
    # Repeat until a unique ID is found
    while True:
        # Generate a random number for patientID
        patient_id = str(random.randint(10000, 99999))  # Adjust range as needed

        # Check if this patientID is already in use
        if not check_patient_id_exists(patient_id):
            return patient_id

def check_patient_id_exists(patient_id):
    # Query Firestore to check if the patientID already exists
    users_ref = db.collection('users')
    query = users_ref.where('patientID', '==', patient_id).limit(1).stream()
    return any(query)

def update_id_map(patient_id, username):
    """
    Update the idmap document in the system_data collection with the patient ID and username.
    """
    idmap_ref = db.collection('system_data').document('idmap')
    # Use a transaction to ensure atomicity
    @firestore.transactional
    def update_in_transaction(transaction, ref, pid, uname):
        snapshot = ref.get(transaction=transaction)
        if snapshot.exists:
            current_map = snapshot.to_dict()
            current_map[pid] = uname
        else:
            current_map = {pid: uname}
        transaction.set(ref, current_map)
    
    transaction = db.transaction()
    update_in_transaction(transaction, idmap_ref, patient_id, username)


def get_username_from_patient_id(patient_id):
    # Assuming you have a 'system_data' collection and an 'idmap' document
    idmap_ref = db.collection('system_data').document('idmap')
    idmap_doc = idmap_ref.get()
    if idmap_doc.exists:
        idmap = idmap_doc.to_dict()
        return idmap.get(patient_id)
    return None


@firestore.transactional
def increment_counter(transaction, counter_ref):
    snapshot = counter_ref.get(transaction=transaction)
    last_number = snapshot.get('last_thread_number')

    if last_number is None:
        last_number = 0
        transaction.set(counter_ref, {'last_thread_number': last_number})

    new_number = last_number + 1
    transaction.update(counter_ref, {'last_thread_number': new_number})
    return new_number

def start_new_thread_with_message(username, message, sender):
    counter_ref = db.collection('users').document(username).collection('feedback').document('thread_counter')
    new_thread_number = increment_counter(db.transaction(), counter_ref)

    new_thread = "thread" + str(new_thread_number)
    now = datetime.now()
    date_str = now.strftime("%d %B %Y")
    time_str = now.strftime("%I:%M %p")

    message_data = {
        'message': message,
        'date': date_str,
        'time': time_str,
        'sender': sender
    }

    doc_ref = db.collection('users').document(username).collection('feedback').document(new_thread)
    doc_ref.set({'messages': [message_data]})


def add_message_to_conversation(username, index, message):
    desired_thread = "thread" + str(index)
    # Get the current datetime
    now = datetime.now()
    # Format date and time (12-hour clock with AM/PM)
    date_str = now.strftime("%d %B %Y")
    time_str = now.strftime("%I:%M %p")  # Format for 12-hour clock with AM/PM

    # Prepare the message data with separate date and time
    message_data = {
        'message': message,
        'date': date_str,
        'time': time_str,
        'sender': username
    }

    # Get a reference to the document
    doc_ref = db.collection('users').document(username).collection('feedback').document(desired_thread)

    # Use set with merge=True to update if exists or create if not exists
    doc_ref.set({'messages': firestore.ArrayUnion([message_data])}, merge=True)

def get_all_conversations(username):
    # Array to hold the first message and count of each thread
    first_messages = []

    # Reference to the user's feedback collection
    feedback_ref = db.collection('users').document(username).collection('feedback')

    # Get all documents (threads) in the feedback collection
    threads = feedback_ref.stream()

    for thread in threads:
        # Get the thread data
        thread_data = thread.to_dict()

        # Check if 'messages' field exists and has at least one message
        if 'messages' in thread_data and thread_data['messages']:
            # Get the count of messages in the thread
            message_count = len(thread_data['messages'])

            # Create a new dict with the 0th message and the count
            first_message_with_count = {
                **thread_data['messages'][0],
                'count': message_count
            }

            # Append this new dict to the array
            first_messages.append(first_message_with_count)

    return first_messages

def get_one_conversation(username, index):
    # Construct the thread ID from the index
    desired_thread = "thread" + str(index)

    # Reference to the specific document (thread) in the user's feedback collection
    thread_ref = db.collection('users').document(username).collection('feedback').document(desired_thread)

    # Attempt to get the document
    thread_doc = thread_ref.get()

    # Check if the document exists and return the 'messages' array if it does
    if thread_doc.exists:
        thread_data = thread_doc.to_dict()
        return thread_data.get('messages', [])  # Return the messages array or an empty array if not found

    # Return None or an empty array if the document does not exist
    return None

if __name__ == '__main__':
    app.run(debug=True)