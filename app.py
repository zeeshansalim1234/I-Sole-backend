from firebase_admin import credentials, initialize_app, firestore
from flask import Flask, Blueprint, request, jsonify, render_template, redirect, url_for
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import pickle
import json
import random
import pyrebase
from datetime import datetime

app = Flask(__name__)
CORS(app,resources={r"/*":{"origins":"*"}})
socketio = SocketIO(app,cors_allowed_origins="*")