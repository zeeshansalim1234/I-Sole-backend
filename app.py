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
import bcrypt


"""
This is the backend code for the I-Sole web application currently hosted on https://i-sole.site/.

The functionalities this backend supports are:

1. Authetication for login/signup
2. Thread-like chatting functionality
3. User Twilio to make emergency calls to patient's notifiers
4. Generates and returns patient's data analytics for Dashboard
5. Retrieve and store data in Firebase Database (NoSQL)
"""

"""App Config Setup"""

app = Flask(__name__)
# CORS(app, resources={r"/*": {"origins": ["https://zeeshansalim1234.github.io"]}})
CORS(app, resources={r"/*": {"origins": "*"}})

cred = credentials.Certificate("i-sole-111bc-firebase-adminsdk-f1xl8-49b2e90098.json")
firebase_admin.initialize_app(cred)
# account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
# auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

db=firestore.client()
# client = Client(account_sid, auth_token)

"""Setup Flask Endpoints"""

@app.route('/initialize_counter', methods=['POST'])
def initialize_counter():
    # This is necessary to keep track of the number of active threads in the chat section
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
        password = signup_data['password']
        patient_id = signup_data.get('patientID', None)  # Optional field

        # Hash the password for security
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

         # Check if the role is 'Patient' and generate a unique patientID
        if role == 'Patient':
            patient_id = generate_unique_patient_id()
            update_id_map(patient_id, username)

        if role == 'Doctor': # add this doct as `myDoctor` for the patient profile
            add_doctor(get_username_from_patient_id(patient_id), username)

        # Create a reference to the Firestore document
        user_ref = db.collection('users').document(username)

        # Create a new document with the provided data
        user_ref.set({
            'email': email,
            'fullName': full_name,
            'username': username,
            'role': role,
            'password': hashed_password.decode('utf-8'),  # Store hashed password as a string
            'patientID': patient_id
        })

        user_data = user_ref.get().to_dict()

        return jsonify({"success": True, "message": "User created successfully", 'user_data': user_data}), 201

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/signin', methods=['POST'])
def signin():
    try:
        # Parse the incoming data from the sign-in form
        signin_data = request.json
        username = signin_data['username']
        password = signin_data['password']
        entered_password = signin_data['password'].encode('utf-8')  # Encode the entered password

        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Attempt to get the document
        user_doc = user_ref.get()

        # Check if the document exists and if the password matches
        if user_doc.exists:
            user_data = user_doc.to_dict()
            stored_password = user_data['password'].encode('utf-8')  # Encode the stored password

            # Compare the entered password with the stored hash
            if bcrypt.checkpw(entered_password, stored_password):
                # Authentication successful
                return jsonify({"success": True, "message": "User signed in successfully", "user_data": user_data}), 200
            else:
                # Authentication failed
                return jsonify({"success": False, "message": "Incorrect password"}), 401
        else:
            # User not found
            return jsonify({"success": False, "message": "User not found"}), 404

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
    # Initializes a new thread to Firebase DB
    data = request.json
    username = data['username']
    sender = data['sender']
    message = data['message']
    start_new_thread_with_message(username, message, sender)
    return jsonify({"success": True})

@app.route('/add_message', methods=['POST'])
def add_message():
    # Appends a message to existing thread in Firebase DB
    data = request.json
    username = data['username']
    index = data['index']
    message = data['message']
    sender = data['sender']
    add_message_to_conversation(username, index, message, sender)
    return jsonify({"success": True})

@app.route('/get_all_conversations/<username>', methods=['GET'])
def get_all(username):
    # Returns all threads for the specific user
    conversations = get_all_conversations(username)
    return jsonify(conversations)

@app.route('/get_one_conversation/<username>/<int:index>', methods=['GET'])
def get_one(username, index):
    # Returns 1 thread for which 'index' is passed, for the provided 'username'
    conversation = get_one_conversation(username, index)
    if conversation is not None:
        return jsonify(conversation)
    else:
        return jsonify({"error": "Conversation not found"}), 404


@app.route('/add_contact', methods=['POST'])
def add_contact():
    # Stores a new emergency contact for the current user in the Firebase DB
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
    # Deletes an existing emergency contact for the current user from the Firebase DB
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


@app.route('/get_my_doctor/<username>', methods=['GET'])
def get_my_doctor(username):
    # Returns the 'doctorName' for the provided 'patientName'
    try:
        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Get the user document data
        user_doc = user_ref.get()

        # Check if the document exists and has the 'myDoctor' field
        if user_doc.exists:
            user_data = user_doc.to_dict()
            my_doctor = user_data.get('myDoctor')
            if my_doctor:
                print(my_doctor)
                return jsonify({"success": True, "myDoctor": my_doctor}), 200
            else:
                return jsonify({"success": False, "message": "myDoctor not found for the user"}), 404
        else:
            return jsonify({"success": False, "message": "User not found"}), 404

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/get_all_contacts/<username>', methods=['GET'])
def get_all_contacts(username):
    # Returns all emergency contact for the provided username
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
    # This essentially sets up the config necessary for making a Twilio call via /voice

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
    callback_url = "https://i-sole-backend.com/voice?message=" + urllib.parse.quote(message)

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
    # Leverages Twilio API to call patient's emergency contact

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


@app.route('/add_pressure_value/<username>', methods=['POST'])
def add_pressure_value(username):
    try:
        # Get pressure value from request
        pressure_value = request.json.get('pressure')

        # Ensure pressure value is provided
        if pressure_value is None:
            return jsonify({"success": False, "message": "Pressure value not provided"}), 400

        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Add pressure value to user's pressureData collection
        user_ref.collection('pressureData').add({
            'pressure': pressure_value,
            'timestamp': firestore.SERVER_TIMESTAMP
        })

        return jsonify({"success": True, "message": "Pressure value added successfully"}), 200

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/get_pressure_data/<username>', methods=['GET'])
def get_pressure_data(username):
    try:
        # Get start and end timestamps from query parameters
        start_timestamp_str = request.args.get('start')
        end_timestamp_str = request.args.get('end')

        # Convert timestamps to datetime objects
        start_timestamp = datetime.fromisoformat(start_timestamp_str)
        end_timestamp = datetime.fromisoformat(end_timestamp_str)

        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Get pressure data collection for the user
        pressure_data_ref = user_ref.collection('pressureData')

        # Query pressure data collection within the specified time range
        pressure_data_docs = pressure_data_ref.where('timestamp', '>=', start_timestamp)\
                                              .where('timestamp', '<=', end_timestamp)\
                                              .order_by('timestamp')\
                                              .get()

        pressure_data = []
        for doc in pressure_data_docs:
            pressure_data.append({
                'pressure': doc.get('pressure'),
                'timestamp': doc.get('timestamp')
            })

        return jsonify({"success": True, "pressureData": pressure_data}), 200

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/add_glucose_value/<username>', methods=['POST'])
def add_glucose_value(username):
    try:
        # Get glucose value from request
        glucose_value = request.json.get('glucose')

        # Ensure glucose value is provided
        if glucose_value is None:
            return jsonify({"success": False, "message": "Glucose value not provided"}), 400

        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Add glucose value to user's glucoseData collection
        user_ref.collection('glucoseData').add({
            'glucose': glucose_value,
            'timestamp': firestore.SERVER_TIMESTAMP
        })

        return jsonify({"success": True, "message": "Glucose value added successfully"}), 200

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/get_glucose_data/<username>', methods=['GET'])
def get_glucose_data(username):
    try:
        # Get start and end timestamps from query parameters
        start_timestamp_str = request.args.get('start')
        end_timestamp_str = request.args.get('end')

        # Convert timestamps to datetime objects
        start_timestamp = datetime.fromisoformat(start_timestamp_str)
        end_timestamp = datetime.fromisoformat(end_timestamp_str)

        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Get glucose data collection for the user
        glucose_data_ref = user_ref.collection('glucoseData')

        # Query glucose data collection within the specified time range
        glucose_data_docs = glucose_data_ref.where('timestamp', '>=', start_timestamp)\
                                              .where('timestamp', '<=', end_timestamp)\
                                              .order_by('timestamp')\
                                              .get()

        glucose_data = []
        for doc in glucose_data_docs:
            glucose_data.append({
                'glucose': doc.get('glucose'),
                'timestamp': doc.get('timestamp')
            })

        return jsonify({"success": True, "glucoseData": glucose_data}), 200

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/add_meal/<username>', methods=['POST'])
def add_meal(username):
    try:
        # Get meal data from request
        meal_data = request.json

        # Ensure required fields are provided
        if 'meal_type' not in meal_data or 'meal_description' not in meal_data:
            return jsonify({"success": False, "message": "Meal data incomplete"}), 400

        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Add meal data to user's meals collection
        user_ref.collection('meals').add({
            'meal_type': meal_data['meal_type'],
            'meal_description': meal_data['meal_description'],
            'timestamp': firestore.SERVER_TIMESTAMP
        })

        return jsonify({"success": True, "message": "Meal added successfully"}), 200

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/get_meals/<username>', methods=['GET'])
def get_meals(username):
    try:
        # Get start and end timestamps from query parameters
        start_timestamp_str = request.args.get('start')
        end_timestamp_str = request.args.get('end')

        # Convert timestamps to datetime objects
        start_timestamp = datetime.fromisoformat(start_timestamp_str)
        end_timestamp = datetime.fromisoformat(end_timestamp_str)

        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Get meals collection for the user
        meals_ref = user_ref.collection('meals')

        # Query meals collection within the specified time range
        meals_docs = meals_ref.where('timestamp', '>=', start_timestamp)\
                              .where('timestamp', '<=', end_timestamp)\
                              .order_by('timestamp', direction='DESCENDING')\
                              .limit(10)\
                              .get()

        meals_data = []
        for doc in meals_docs:
            meals_data.append({
                'meal_type': doc.get('meal_type'),
                'timestamp': doc.get('timestamp'),
                'meal_description': doc.get('meal_description')
            })

        return jsonify({"success": True, "mealsData": meals_data}), 200

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    

@app.route('/add_blood_glucose_level', methods=['POST'])
def add_blood_glucose_level():
    try:
        # Parse the request data
        username = request.json.get('username')
        bloodGlucoseLevel = request.json.get('bloodGlucoseLevel')
        
        # Check if the document exists
        personal_metrics_ref = db.collection('users').document(username).collection('personal-metrics').document('personal-info')
        personal_info_data = personal_metrics_ref.get().to_dict()
        
        if personal_info_data:
           personal_metrics_ref.update({'blood_glucose_level': bloodGlucoseLevel})
           # Return success response
           return jsonify({"success": True}), 200

        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document personal_info does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/update_weight', methods=['POST'])
def update_weight():
    try:
        # Parse the request data
        username = request.json.get('username')
        weight = request.json.get('weight')
        # Check if the document exists
        personal_metrics_ref = db.collection('users').document(username).collection('personal-metrics').document('personal-info')
        personal_info_data = personal_metrics_ref.get().to_dict()
        if personal_info_data:
           personal_metrics_ref.update({'weight': weight})
           # Return success response
           return jsonify({"success": True}), 200
        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document personal_info does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/update_height', methods=['POST'])
def update_height():
    try:
        # Parse the request data
        username = request.json.get('username')
        height = request.json.get('height')
        # Check if the document exists
        personal_metrics_ref = db.collection('users').document(username).collection('personal-metrics').document('personal-info')
        personal_info_data = personal_metrics_ref.get().to_dict()
        if personal_info_data:
           personal_metrics_ref.update({'height': height})
           # Return success response
           return jsonify({"success": True}), 200
        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document personal_info does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/update_insulin_dosage', methods=['POST'])
def update_insulin_dosage():
    try:
        # Parse the request data
        username = request.json.get('username')
        insulinDosage = request.json.get('insulinDosage')
        # Check if the document exists
        personal_metrics_ref = db.collection('users').document(username).collection('personal-metrics').document('personal-info')
        personal_info_data = personal_metrics_ref.get().to_dict()
        if personal_info_data:
           personal_metrics_ref.update({'insulin_dosage': insulinDosage})
           # Return success response
           return jsonify({"success": True}), 200
        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document personal_info does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/update_allergies', methods=['POST'])
def update_allergies():
    try:
        # Parse the request data
        username = request.json.get('username')
        allergies = request.json.get('allergies')
        # Check if the document exists
        personal_metrics_ref = db.collection('users').document(username).collection('personal-metrics').document('personal-info')
        personal_info_data = personal_metrics_ref.get().to_dict()
        if personal_info_data:
           personal_metrics_ref.update({'allergies': allergies})
           # Return success response
           return jsonify({"success": True}), 200
        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document personal_info does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/update_name', methods=['POST'])
def update_name():
    try:
        # Parse the request data
        username = request.json.get('username')
        name = request.json.get('name')
        
        # Check if the document exists
        users_ref = db.collection('users').document(username)
        profile_data = users_ref.get().to_dict()
        
        if profile_data:
           users_ref.update({'fullName': name})
           # Return success response
           return jsonify({"success": True}), 200

        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/update_email', methods=['POST'])
def update_email():
    try:
        # Parse the request data
        username = request.json.get('username')
        email = request.json.get('email')
        
        # Check if the document exists
        users_ref = db.collection('users').document(username)
        profile_data = users_ref.get().to_dict()
        
        if profile_data:
           users_ref.update({'email': email})
           # Return success response
           return jsonify({"success": True}), 200

        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/update_phone_number', methods=['POST'])
def update_phone_number():
    try:
        # Parse the request data
        username = request.json.get('username')
        phoneNumber = request.json.get('phoneNumber')
        
        # Check if the document exists
        users_ref = db.collection('users').document(username)
        profile_data = users_ref.get().to_dict()
        
        if profile_data:
           users_ref.update({'phoneNumber': phoneNumber})
           # Return success response
           return jsonify({"success": True}), 200

        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/update_date_of_birth', methods=['POST'])
def update_date_of_birth():
    try:
        # Parse the request data
        username = request.json.get('username')
        dateOfBirth = request.json.get('dateOfBirth')
        
        # Check if the document exists
        users_ref = db.collection('users').document(username)
        profile_data = users_ref.get().to_dict()
        
        if profile_data:
           users_ref.update({'dateOfBirth': dateOfBirth})
           # Return success response
           return jsonify({"success": True}), 200

        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/update_emergency_contact', methods=['POST'])
def update_emergency_contact():
    try:
        # Parse the request data
        username = request.json.get('username')
        emergencyContact = request.json.get('emergencyContact')
        
        # Check if the document exists
        users_ref = db.collection('users').document(username)
        profile_data = users_ref.get().to_dict()
        
        if profile_data:
           users_ref.update({'emergencyContact': emergencyContact})
           # Return success response
           return jsonify({"success": True}), 200

        else:
            # Document doesn't exist, return error response
            return jsonify({"success": False, "message": "Document does not exist for user: " + username}), 404
        
    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/get_profile_data/<username>', methods=['GET'])
def get_profile_data(username):
    try:
        # Reference to the Firestore document of the user
        user_ref = db.collection('users').document(username)

        # Get the user document data
        user_doc = user_ref.get()

        # Check if the document exists
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return jsonify({"success": True, "data": user_data}), 200  # Set success to True and include data
        else:
            return jsonify({"success": False, "message": "User not found"}), 404

    except Exception as e:
        # Handle exceptions
        return jsonify({"success": False, "message": str(e)}), 500

    

"""Helper Methods"""

def add_doctor(username, doctorName):
    # Reference to the Firestore document of the user
    user_ref = db.collection('users').document(username)

    # Update the user document to add the 'myDoctor' field
    user_ref.update({'myDoctor': doctorName})

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


def add_message_to_conversation(username, index, message, sender):
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
        'sender': sender
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
    # app.run(debug=True)
    app.run(host='0.0.0.0', port=5002)