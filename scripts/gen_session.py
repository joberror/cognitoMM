from pyrogram import Client

API_ID = int(input("Enter your API_ID: "))
API_HASH = input("Enter your API_HASH: ")

with Client(name="gen", api_id=API_ID, api_hash=API_HASH) as app:
    session_string = app.export_session_string()
    print("\n✅ Your Kurigram SESSION_STRING:\n")
    print(session_string)
