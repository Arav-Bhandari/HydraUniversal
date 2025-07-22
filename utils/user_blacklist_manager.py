import json
import os
import logging
from typing import List, Dict, Set

logger = logging.getLogger('bot.user_blacklist_manager')

class UserBlacklistManager:
    def __init__(self, data_file: str = "data/user_blacklists.json"):
        self.data_file = data_file
        self.blacklists = self._load_data()

    def _load_data(self) -> Dict:
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        logger.info(f"User blacklist file '{self.data_file}' is empty. Initializing with empty dict.")
                        return {}
                    return json.load(f)
            else:
                logger.info(f"User blacklist file '{self.data_file}' not found. Initializing with empty dict and creating directory if needed.")
                os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
                return {}
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from '{self.data_file}'. Returning empty dict.")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error loading user blacklist data from '{self.data_file}': {e}")
            return {}

    def _save_data(self) -> None:
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.blacklists, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving user blacklist data to '{self.data_file}': {e}")

    def _get_guild_blacklists(self, guild_id: str) -> Dict:
        guild_id = str(guild_id)
        if guild_id not in self.blacklists:
            self.blacklists[guild_id] = {"applications": {}, "tickets": {}}
        return self.blacklists[guild_id]

    def _get_user_app_blacklist_set(self, guild_id: str, user_id: str) -> Set[str]:
        user_id = str(user_id)
        guild_bl = self._get_guild_blacklists(guild_id)
        if user_id not in guild_bl["applications"]:
            guild_bl["applications"][user_id] = []
        return set(guild_bl["applications"][user_id])

    def _get_user_ticket_blacklist_set(self, guild_id: str, user_id: str) -> Set[str]:
        user_id = str(user_id)
        guild_bl = self._get_guild_blacklists(guild_id)
        if user_id not in guild_bl["tickets"]:
            guild_bl["tickets"][user_id] = []
        return set(guild_bl["tickets"][user_id])

    def add_application_blacklist(self, guild_id: str, user_id: str, app_type_id: str) -> None:
        guild_id, user_id, app_type_id = str(guild_id), str(user_id), str(app_type_id)
        user_app_bl_set = self._get_user_app_blacklist_set(guild_id, user_id)
        user_app_bl_set.add(app_type_id)
        self.blacklists[guild_id]["applications"][user_id] = sorted(list(user_app_bl_set))
        self._save_data()
        logger.info(f"User {user_id} blacklisted from application type {app_type_id} in guild {guild_id}")

    def remove_application_blacklist(self, guild_id: str, user_id: str, app_type_id: str) -> None:
        guild_id, user_id, app_type_id = str(guild_id), str(user_id), str(app_type_id)
        user_app_bl_set = self._get_user_app_blacklist_set(guild_id, user_id)
        user_app_bl_set.discard(app_type_id)
        self.blacklists[guild_id]["applications"][user_id] = sorted(list(user_app_bl_set))
        if not self.blacklists[guild_id]["applications"][user_id]: # cleanup if empty list
            del self.blacklists[guild_id]["applications"][user_id]
        self._save_data()
        logger.info(f"User {user_id} unblacklisted from application type {app_type_id} in guild {guild_id}")

    def add_ticket_blacklist(self, guild_id: str, user_id: str, ticket_category_id: str) -> None:
        guild_id, user_id, ticket_category_id = str(guild_id), str(user_id), str(ticket_category_id)
        user_ticket_bl_set = self._get_user_ticket_blacklist_set(guild_id, user_id)
        user_ticket_bl_set.add(ticket_category_id)
        self.blacklists[guild_id]["tickets"][user_id] = sorted(list(user_ticket_bl_set))
        self._save_data()
        logger.info(f"User {user_id} blacklisted from ticket category {ticket_category_id} in guild {guild_id}")

    def remove_ticket_blacklist(self, guild_id: str, user_id: str, ticket_category_id: str) -> None:
        guild_id, user_id, ticket_category_id = str(guild_id), str(user_id), str(ticket_category_id)
        user_ticket_bl_set = self._get_user_ticket_blacklist_set(guild_id, user_id)
        user_ticket_bl_set.discard(ticket_category_id)
        self.blacklists[guild_id]["tickets"][user_id] = sorted(list(user_ticket_bl_set))
        if not self.blacklists[guild_id]["tickets"][user_id]: # cleanup if empty list
            del self.blacklists[guild_id]["tickets"][user_id]
        self._save_data()
        logger.info(f"User {user_id} unblacklisted from ticket category {ticket_category_id} in guild {guild_id}")

    def is_application_blacklisted(self, guild_id: str, user_id: str, app_type_id: str) -> bool:
        guild_id, user_id, app_type_id = str(guild_id), str(user_id), str(app_type_id)
        user_app_bl_set = self._get_user_app_blacklist_set(guild_id, user_id)
        return app_type_id in user_app_bl_set

    def is_ticket_blacklisted(self, guild_id: str, user_id: str, ticket_category_id: str) -> bool:
        guild_id, user_id, ticket_category_id = str(guild_id), str(user_id), str(ticket_category_id)
        user_ticket_bl_set = self._get_user_ticket_blacklist_set(guild_id, user_id)
        return ticket_category_id in user_ticket_bl_set

    def get_user_application_blacklists(self, guild_id: str, user_id: str) -> List[str]:
        guild_id, user_id = str(guild_id), str(user_id)
        # Ensure internal representation is list, not set, before returning
        return list(self._get_user_app_blacklist_set(guild_id, user_id))


    def get_user_ticket_blacklists(self, guild_id: str, user_id: str) -> List[str]:
        guild_id, user_id = str(guild_id), str(user_id)
        # Ensure internal representation is list, not set, before returning
        return list(self._get_user_ticket_blacklist_set(guild_id, user_id))