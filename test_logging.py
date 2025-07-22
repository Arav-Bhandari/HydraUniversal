import discord
import asyncio
from utils.logging import log_action

class MockGuild:
    def __init__(self, id):
        self.id = id
        
    def get_channel(self, channel_id):
        return None

class MockUser:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        
    def __str__(self):
        return self.name

async def test_logging():
    guild = MockGuild(999999)
    user = MockUser(123456, 'Test User')
    log_id = await log_action(guild, 'TEST', user, 'This is a test action', 'test_command')
    print(f'Log created with ID: {log_id}')
    
    if log_id:
        print('Logging is working correctly')
    else:
        print('Logging failed')

if __name__ == "__main__":
    asyncio.run(test_logging())