import uuid

NEW_TOKEN = str(uuid.uuid4())

with open('session_token.txt', 'w') as f:
    f.write(NEW_TOKEN)

print("All sessions invalidated. Everyone will be forced to re-login.")