import json
import os
import logging

# Define logger at the module level so it's accessible by all functions here
logger = logging.getLogger("bot.config")

def load_json(filename: str) -> dict:
    """Load JSON data from file in the 'data' subdirectory."""
    try:
        filepath = os.path.join("data", filename)
        if not os.path.exists(filepath):
            logger.info(f"File not found: {filepath}. Returning empty dictionary.")
            return {}
        with open(filepath, "r", encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                logger.info(f"File is empty: {filepath}. Returning empty dictionary.")
                return {}
            return json.loads(content)
    except FileNotFoundError:
        logger.info(f"FileNotFoundError: {filepath}. Returning empty dictionary.")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {filepath}: {e}. Returning empty dictionary.")
        return {}
    except Exception as e:
        logger.error(f"An unexpected error occurred loading {filepath}: {e}. Returning empty dictionary.")
        return {}

def save_json(filename: str, data: dict) -> None:
    """Save JSON data to file in the 'data' subdirectory."""
    try:
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            logger.info(f"Created directory: {data_dir}")

        filepath = os.path.join(data_dir, filename)
        with open(filepath, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        logger.debug(f"Successfully saved data to {filepath}")
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")

def get_default_config() -> dict:
    """Get default server configuration structure."""
    return {
        "log_channels": {}, # e.g., {"transactions": "id", "games": "id", "mod_actions": "id"}
        "notification_settings": {
            "channel_notifications": True,
            "dm_notifications": True,
            "staff_notifications": True,
            "game_reminders": True,
            "reminder_48h": True, "reminder_24h": True, "reminder_3h": True,
            "reminder_1h": True, "reminder_30m": True, "reminder_10m": True
        },
        "permission_settings": {
            "admin_roles": [],
            "moderator_roles": [],
            "gm_roles": [],
            "hc_roles": [],
            "ac_roles": [],
            "fo_roles": [],
            "candidate_roles": [],
            "referee_roles": [],
            "streamer_roles": [],
            "manage_teams_roles": [],
            # New role types added below
            "blacklisted_roles": [],
            "suspension_roles": [],
            "ticket_blacklisted_roles": [],
            "free_agent_roles": []
        },
        "announcement_channels": {
             "announcements_channel_id": None,
             "reminders_channel_id": None,
        },
        "reporting_settings": { # New section for silver game reporting channels
            "silver_game_report_channel": None, # For /scorereport
            "silver_game_leaderboard_channel": None # For /leaderboard (player stats)
        },
        "team_records": {}, # For silver game team W-L-T records e.g. {"TeamA": {"wins": 0, "losses": 0, "ties": 0}}
        "enabled_commands": {},
        "team_data": {},
        "team_roles": {},
        "roster_cap": 53,
    }

def get_server_config(guild_id) -> dict:
    """Get a specific guild's configuration, ensuring it has all default keys."""
    configs = load_json("serverconfig.json")
    guild_id_str = str(guild_id)

    guild_config = configs.get(guild_id_str)
    needs_save = False

    if guild_config is None:
        guild_config = get_default_config()
        configs[guild_id_str] = guild_config
        needs_save = True
        logger.info(f"Created new default config for guild {guild_id_str}.")
    else:
        # Ensure all default keys are present by deep merging/checking
        default_conf_template = get_default_config()

        # Use a temporary copy for iteration if modifying during iteration is an issue
        # For simple key addition, direct modification is fine. For deep merge, more care is needed.

        # Check and add missing top-level keys
        for key, default_value in default_conf_template.items():
            if key not in guild_config:
                guild_config[key] = default_value
                needs_save = True
                logger.info(f"Guild {guild_id_str}: Added missing top-level key '{key}'.")
            # If the key exists, ensure its type matches, especially for dicts (like permission_settings)
            elif isinstance(default_value, dict) and isinstance(guild_config.get(key), dict):
                # Check for missing second-level keys within this dict
                for sub_key, sub_default_value in default_value.items():
                    if sub_key not in guild_config[key]:
                        guild_config[key][sub_key] = sub_default_value
                        needs_save = True
                        logger.info(f"Guild {guild_id_str}: Added missing sub-key '{sub_key}' in '{key}'.")
            elif isinstance(default_value, dict) and not isinstance(guild_config.get(key), dict):
                # If the type is wrong for a dict, reset to default to ensure structure
                logger.warning(f"Guild {guild_id_str}: Correcting type for key '{key}'. Expected dict, got {type(guild_config.get(key)).__name__}. Resetting to default for this key.")
                guild_config[key] = default_value
                needs_save = True


    if needs_save:
        save_json("serverconfig.json", configs)

    return guild_config

def update_server_config(guild_id, key: str, value) -> None:
    """Update a specific top-level key in a guild's configuration."""
    configs = load_json("serverconfig.json")
    guild_id_str = str(guild_id)

    # Ensure the guild's config exists and is fully populated before modification
    # This leverages get_server_config's logic to create/update if necessary
    current_guild_config = get_server_config(guild_id)
    configs[guild_id_str] = current_guild_config # Get the potentially updated config back

    configs[guild_id_str][key] = value # Apply the specific update
    save_json("serverconfig.json", configs)
    logger.debug(f"Updated config for guild {guild_id_str}: set {key} to {value}")

def save_guild_config(guild_id, guild_config_data: dict) -> None:
    """Save the entire configuration object for a specific guild."""
    configs = load_json("serverconfig.json")
    guild_id_str = str(guild_id)
    configs[guild_id_str] = guild_config_data
    save_json("serverconfig.json", configs)
    logger.debug(f"Saved full config for guild {guild_id_str}.")

def _deep_clean_dict(original_dict: dict, default_struct: dict, dict_path: str = "") -> tuple[dict, bool]:
    """
    Recursively cleans a dictionary against a default structure.
    Ensures only keys from default_struct exist, and their values match types.
    Returns the cleaned dictionary and a boolean indicating if changes were made.
    """
    if not isinstance(original_dict, dict):
        logger.warning(f"Path '{dict_path}': Expected dict, got {type(original_dict).__name__}. Resetting.")
        return default_struct.copy(), True

    if not isinstance(default_struct, dict):
         logger.error(f"Path '{dict_path}': Default structure is not dict ({type(default_struct).__name__}). Cannot clean.")
         return original_dict, False

    cleaned_dict = {}
    modified = False

    default_keys = set(default_struct.keys())
    original_keys = set(original_dict.keys())

    for key, default_value in default_struct.items():
        current_path = f"{dict_path}.{key}" if dict_path else key
        if key not in original_dict:
            cleaned_dict[key] = default_value
            modified = True
            logger.info(f"Path '{current_path}': Added missing key '{key}'.")
        elif isinstance(default_value, dict):
            # Ensure the original value for the key is also a dict before recursing
            original_subkey_val = original_dict.get(key, {})
            if not isinstance(original_subkey_val, dict):
                logger.warning(f"Path '{current_path}': Expected dict for key '{key}', got {type(original_subkey_val).__name__}. Resetting this sub-dict.")
                cleaned_nested_dict, nested_modified = default_value.copy(), True
            else:
                cleaned_nested_dict, nested_modified = _deep_clean_dict(original_subkey_val, default_value, current_path)

            cleaned_dict[key] = cleaned_nested_dict
            if nested_modified:
                modified = True
        # Handle None being corrected to empty list for list types
        elif original_dict.get(key) is None and isinstance(default_value, list):
            cleaned_dict[key] = []
            modified = True
            logger.warning(f"Path '{current_path}': Corrected key '{key}' from None to [].")
        # Type correction, but be careful not to overwrite if original_dict.get(key) is None and default_value is not None (unless list handled above)
        elif default_value is not None and original_dict.get(key) is not None and \
             not isinstance(original_dict.get(key), type(default_value)):
            logger.warning(f"Path '{current_path}': Correcting type for '{key}' from {type(original_dict.get(key)).__name__} to {type(default_value).__name__}.")
            cleaned_dict[key] = default_value
            modified = True
        else:
            cleaned_dict[key] = original_dict.get(key) # Keep original value

    extraneous_keys = original_keys - default_keys
    if extraneous_keys:
        for key in extraneous_keys:
            logger.info(f"Path '{dict_path}': Removed extraneous key '{key}'.")
        modified = True

    return cleaned_dict, modified

def clean_server_configs():
    """
    Loads serverconfig.json, cleans each guild's configuration.
    Conforms to default structure, removes extraneous keys, adds missing ones, corrects types.
    Uses deep cleaning for nested dictionaries.
    Saves back if changes were made. Returns a summary.
    """
    configs = load_json("serverconfig.json")
    if not configs or not isinstance(configs, dict):
        logger.warning("serverconfig.json empty/invalid. No cleaning.")
        return "No server configurations to clean or file is invalid."

    default_config_structure = get_default_config()
    summary = {"guilds_processed": 0, "guilds_repaired_or_updated": 0}
    any_changes_made_to_overall_file = False

    for guild_id, guild_cfg in list(configs.items()):
        summary["guilds_processed"] += 1

        if not isinstance(guild_cfg, dict):
            logger.warning(f"Guild {guild_id}: Config is {type(guild_cfg).__name__}, not dict. Replacing with default.")
            configs[guild_id] = get_default_config()
            summary["guilds_repaired_or_updated"] += 1
            any_changes_made_to_overall_file = True
            continue

        cleaned_guild_cfg, guild_modified = _deep_clean_dict(guild_cfg, default_config_structure, f"Guild({guild_id})")

        if guild_modified:
            configs[guild_id] = cleaned_guild_cfg
            summary["guilds_repaired_or_updated"] += 1
            any_changes_made_to_overall_file = True

    if any_changes_made_to_overall_file:
        save_json("serverconfig.json", configs)
        return (f"Config cleaning done. Processed: {summary['guilds_processed']}. "
                f"Repaired/Updated: {summary['guilds_repaired_or_updated']}. See logs for details.")
    else:
        return f"Config cleaning done. Processed: {summary['guilds_processed']}. No changes needed."