import json
import bcrypt
import uuid
from flask import session

with open('users.json') as f:
    USERS = json.load(f)

# Generated fresh every time the server starts.
# Any session missing this token is from a previous run → force logout.
SERVER_SESSION_TOKEN = str(uuid.uuid4())

def check_login(username, password):
    user = USERS.get(username)
    if not user:
        return False
    
    stored_hash = user['password'].encode('utf-8')
    input_password = password.encode('utf-8')
    
    return bcrypt.checkpw(input_password, stored_hash)

def get_role(username):
    user = USERS.get(username)
    if user:
        return user.get('role')
    return None

def login_user(username):
    session.clear()
    session['username'] = username
    session['role'] = get_role(username)
    session['logged_in'] = True
    session['server_token'] = SERVER_SESSION_TOKEN  # Stamp the current server run

def logout_user():
    session.clear()

def current_user():
    return session.get('username')

def is_logged_in():
    username = session.get('username')
    if not username or not session.get('logged_in'):
        return False
    if session.get('server_token') != SERVER_SESSION_TOKEN:  # Server was restarted
        session.clear()                                       # Force logout
        return False
    return username in USERS  # Invalidates sessions for deleted users