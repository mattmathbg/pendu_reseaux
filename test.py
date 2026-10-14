from core.session import GameSession

session = GameSession(player_name="Alice")
print(f"Session ID: {session.session_id}")
print(f"Auth Token: {session.auth_token}")
print(f"Player Name: {session.player_name}")
print(f"Is Connected: {session.is_connected}")
print(f"Disconnect Timestamp: {session.disconnect_timestamp}")
