import json
import bcrypt
import uuid
from flask import session

with open('users.json') as f:
    USERS = json.load(f)

def _get_server_token():
    try:
        with open('session_token.txt') as f:
            return f.read().strip()
    except FileNotFoundError:
        # First run — generate and save one
        token = str(uuid.uuid4())
        with open('session_token.txt', 'w') as f:
            f.write(token)
        return token

def check_login(username, password):
    with open('users.json') as f:   # Fresh read every time
        users = json.load(f)
    user = users.get(username)
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
    session.permanent = True                            # Enables cookie lifetime from app.py
    session['username'] = username
    session['role'] = get_role(username)
    session['logged_in'] = True
    session['server_token'] = _get_server_token()      # Stamp current token from file

def logout_user():
    session.clear()

def current_user():
    return session.get('username')

def is_logged_in():
    username = session.get('username')
    if not username or not session.get('logged_in'):
        return False
    if session.get('server_token') != _get_server_token():  # Compare against file
        session.clear()                                       # Force logout
        return False
    return username in USERS  # Invalidates sessions for deleted users