import json
import bcrypt
from flask import session

with open('users.json') as f:
    USERS = json.load(f)

def check_login(username, password):
    user = USERS.get(username)
    if not user:
        return False
    
    # The stored password is already a string, so we need to encode it back to bytes
    # The input password needs to be encoded to bytes as well
    stored_hash = user['password'].encode('utf-8')  # Convert string back to bytes
    input_password = password.encode('utf-8')       # Convert input to bytes
    
    return bcrypt.checkpw(input_password, stored_hash)

def get_role(username):
    user = USERS.get(username)
    if user:
        return user.get('role')
    return None

def login_user(username):
    session['username'] = username

def logout_user():
    session.pop('username', None)

def current_user():
    return session.get('username')

def is_logged_in():
    return 'username' in session