import gspread
import asyncio
import threading
import logging
import json
import os
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

logger = logging.getLogger("bot.sheets")

# Thread lock for Google Sheets operations
sheets_lock = threading.Lock()

# Ensure credentials file exists
if not os.path.exists("data/credentials.json"):
    try:
        # Create dummy credentials file for now (will be replaced with actual credentials)
        dummy_creds = {
            "type": "service_account",
            "project_id": "league-bot",
            "private_key_id": "dummy",
            "private_key": "-----BEGIN PRIVATE KEY-----\ndummy\n-----END PRIVATE KEY-----\n",
            "client_email": "dummy@league-bot.iam.gserviceaccount.com",
            "client_id": "dummy",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": "dummy"
        }
        os.makedirs("data", exist_ok=True)
        with open("data/credentials.json", "w") as f:
            json.dump(dummy_creds, f, indent=4)
        logger.warning("Created dummy credentials.json - replace with actual credentials")
    except Exception as e:
        logger.error(f"Failed to create dummy credentials: {e}")

def get_sheet_client():
    """Get an authorized Google Sheets client."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("data/credentials.json", scope)
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets client: {e}")
        return None

def open_sheet_by_url(client, url):
    """Open a Google Sheet by URL."""
    try:
        if not client:
            return None
        return client.open_by_url(url)
    except gspread.exceptions.APIError as api_err:
        logger.error(f"Google Sheets API error: {api_err}")
        return None
    except Exception as e:
        logger.error(f"Failed to open sheet: {e}")
        return None

def find_player_row(worksheet, player):
    """Find the row for a player in the worksheet."""
    try:
        if not worksheet:
            raise ValueError("Invalid Worksheet")
        cell = worksheet.find(player, in_column=1)
        return cell.row if cell else None
    except gspread.exceptions.APIError as api_err:
        logger.error(f"Google Sheets API error: {api_err}")
        raise Exception(f"Google Sheets API error: {api_err}")
    except AttributeError:
        try:
            values = worksheet.col_values(1)
            for i, val in enumerate(values):
                if val and val.lower() == player.lower():
                    return i + 1
            return None
        except Exception as e:
            logger.error(f"Error searching for player in worksheet: {e}")
            raise Exception(f"Error searching for player in worksheet: {e}")
    except Exception as e:
        logger.error(f"Failed to find player row: {e}")
        raise Exception(f"Failed to find player row: {e}")

def get_next_row(worksheet, max_rows=1000):
    """Get the next available row in the worksheet."""
    try:
        values = worksheet.col_values(1)
        last_row = len(values)
        while last_row > 0 and not values[last_row - 1]:
            last_row -= 1
        next_row = last_row + 1
        if next_row > max_rows:
            raise Exception("No available rows within the sheet's bounds")
        return next_row
    except gspread.exceptions.APIError as api_err:
        logger.error(f"Google Sheets API error: {api_err}")
        raise Exception(f"Google Sheets API error: {api_err}")
    except Exception as e:
        logger.error(f"Failed to find next row: {e}")
        raise Exception(f"Failed to find next row: {e}")

def safe_int(value, default=0):
    """Safely convert a value to an integer."""
    if not value or value == "":
        return default
    if isinstance(value, str) and "%" in value:
        try:
            return int(float(value.strip("%")))
        except ValueError:
            return default
    try:
        return int(value)
    except ValueError:
        return default

async def update_qb_stats(sheet_url, player, comp, att, yards, tds, ints, sacks):
    """Update quarterback stats in the Google Sheet."""
    def _update():
        with sheets_lock:
            client = get_sheet_client()
            sheet = open_sheet_by_url(client, sheet_url)
            if not sheet:
                raise Exception("Could not open sheet")
            
            worksheet = sheet.worksheet("QB Stats")
            row = find_player_row(worksheet, player)

            def calculate_qbr(comp, att, yards, tds, ints):
                a = max(0, min(2.375, ((comp / att) * 100 - 30) * 0.05)) if att > 0 else 0
                b = max(0, min(2.375, ((yards / att) - 3) * 0.25)) if att > 0 else 0
                c = max(0, min(2.375, (tds / att) * 20)) if att > 0 else 0
                d = max(0, min(2.375, 2.375 - ((ints / att) * 25))) if att > 0 else 0
                return ((a + b + c + d) / 6) * 100

            updates = []
            qbr = None
            if row:
                current_stats = worksheet.row_values(row)
                new_comp = safe_int(current_stats[2]) + comp
                new_att = safe_int(current_stats[3]) + att
                new_yards = safe_int(current_stats[5]) + yards
                new_tds = safe_int(current_stats[6]) + tds
                new_ints = safe_int(current_stats[7]) + ints
                new_sacks = safe_int(current_stats[9]) + sacks
                new_comp_pct = (new_comp / new_att) if new_att > 0 else 0
                new_int_pct = (new_ints / new_att) if new_att > 0 else 0
                qbr = calculate_qbr(new_comp, new_att, new_yards, new_tds, new_ints)
                updates.append({
                    "range": f"A{row}:J{row}",
                    "values": [[player, qbr, new_comp, new_att, new_comp_pct, new_yards, new_tds, new_ints, new_int_pct, new_sacks]]
                })
            else:
                comp_pct = (comp / att) if att > 0 else 0
                int_pct = (ints / att) if att > 0 else 0
                qbr = calculate_qbr(comp, att, yards, tds, ints)
                next_row = get_next_row(worksheet)
                updates.append({
                    "range": f"A{next_row}:J{next_row}",
                    "values": [[player, qbr, comp, att, comp_pct, yards, tds, ints, int_pct, sacks]]
                })

            worksheet.batch_update(updates)
            return qbr

    try:
        qbr = await asyncio.to_thread(_update)
        return qbr
    except Exception as e:
        logger.error(f"Failed to update QB stats: {e}")
        raise Exception(f"Failed to update QB stats: {e}")

async def update_wr_stats(sheet_url, player, catches, targets, tds, yac, yards):
    """Update wide receiver stats in the Google Sheet."""
    def _update():
        with sheets_lock:
            client = get_sheet_client()
            sheet = open_sheet_by_url(client, sheet_url)
            if not sheet:
                raise Exception("Could not open sheet")
            
            worksheet = sheet.worksheet("WR Stats")
            row = find_player_row(worksheet, player)
            updates = []
            if row:
                current_stats = worksheet.row_values(row)
                new_catches = safe_int(current_stats[1]) + catches
                new_targets = safe_int(current_stats[2]) + targets
                new_tds = safe_int(current_stats[4]) + tds
                new_yac = safe_int(current_stats[5]) + yac
                new_yards = safe_int(current_stats[6]) + yards
                new_catch_pct = (new_catches / new_targets) if new_targets > 0 else 0
                new_ypc = (new_yards / new_catches) if new_catches > 0 else 0
                updates.append({
                    "range": f"A{row}:H{row}",
                    "values": [[player, new_catches, new_targets, new_catch_pct, new_tds, new_yac, new_yards, new_ypc]]
                })
            else:
                catch_pct = (catches / targets) if targets > 0 else 0
                ypc = (yards / catches) if catches > 0 else 0
                next_row = get_next_row(worksheet)
                updates.append({
                    "range": f"A{next_row}:H{next_row}",
                    "values": [[player, catches, targets, catch_pct, tds, yac, yards, ypc]]
                })

            worksheet.batch_update(updates)

    try:
        await asyncio.to_thread(_update)
    except Exception as e:
        logger.error(f"Failed to update WR stats: {e}")
        raise Exception(f"Failed to update WR stats: {e}")

async def update_cb_stats(sheet_url, player, ints, targets, swats, tds, comp_allowed):
    """Update cornerback stats in the Google Sheet."""
    def _update():
        with sheets_lock:
            client = get_sheet_client()
            sheet = open_sheet_by_url(client, sheet_url)
            if not sheet:
                raise Exception("Could not open sheet")
            
            worksheet = sheet.worksheet("CB Stats")
            row = find_player_row(worksheet, player)
            updates = []
            if row:
                current_stats = worksheet.row_values(row)
                new_ints = safe_int(current_stats[1]) + ints
                new_targets = safe_int(current_stats[3]) + targets
                new_swats = safe_int(current_stats[4]) + swats
                new_tds = safe_int(current_stats[5]) + tds
                new_comp_allowed = safe_int(current_stats[6]) + comp_allowed
                new_deny_pct = (new_swats / new_targets) if new_targets > 0 else 0
                new_comp_pct = (new_comp_allowed / new_targets) if new_targets > 0 else 0
                updates.append({
                    "range": f"A{row}:H{row}",
                    "values": [[player, new_ints, new_deny_pct, new_targets, new_swats, new_tds, new_comp_allowed, new_comp_pct]]
                })
            else:
                deny_pct = (swats / targets) if targets > 0 else 0
                comp_pct = (comp_allowed / targets) if targets > 0 else 0
                next_row = get_next_row(worksheet)
                updates.append({
                    "range": f"A{next_row}:H{next_row}",
                    "values": [[player, ints, deny_pct, targets, swats, tds, comp_allowed, comp_pct]]
                })

            worksheet.batch_update(updates)

    try:
        await asyncio.to_thread(_update)
    except Exception as e:
        logger.error(f"Failed to update CB stats: {e}")
        raise Exception(f"Failed to update CB stats: {e}")

async def update_de_stats(sheet_url, player, tackles, misses, sacks, safeties):
    """Update defensive end stats in the Google Sheet."""
    def _update():
        with sheets_lock:
            client = get_sheet_client()
            sheet = open_sheet_by_url(client, sheet_url)
            if not sheet:
                raise Exception("Could not open sheet")
            
            worksheet = sheet.worksheet("DE Stats")
            row = find_player_row(worksheet, player)
            updates = []
            if row:
                current_stats = worksheet.row_values(row)
                new_tackles = safe_int(current_stats[1]) + tackles
                new_misses = safe_int(current_stats[2]) + misses
                new_sacks = safe_int(current_stats[3]) + sacks
                new_safeties = safe_int(current_stats[4]) + safeties
                updates.append({
                    "range": f"A{row}:E{row}",
                    "values": [[player, new_tackles, new_misses, new_sacks, new_safeties]]
                })
            else:
                next_row = get_next_row(worksheet)
                updates.append({
                    "range": f"A{next_row}:E{next_row}",
                    "values": [[player, tackles, misses, sacks, safeties]]
                })

            worksheet.batch_update(updates)

    try:
        await asyncio.to_thread(_update)
    except Exception as e:
        logger.error(f"Failed to update DE stats: {e}")
        raise Exception(f"Failed to update DE stats: {e}")

async def check_sheet_access(sheet_url):
    """Check if the bot has access to the sheet."""
    try:
        def _check():
            with sheets_lock:
                client = get_sheet_client()
                sheet = open_sheet_by_url(client, sheet_url)
                return sheet is not None
        
        return await asyncio.to_thread(_check)
    except Exception as e:
        logger.error(f"Sheet access check failed: {e}")
        return False
