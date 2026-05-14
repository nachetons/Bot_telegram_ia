"""Compatibilidad con código existente - delega a ChatStateManager."""

from app.core.state_manager import state_manager as manager

# Pending Followups
get_pending_followup = manager.get_pending_followup
set_pending_followup = manager.set_pending_followup
pop_pending_followup = manager.pop_pending_followup
clear_pending_followup = manager.clear_pending_followup

# Prediction Sessions
set_prediction_session = manager.set_prediction_session
get_prediction_session = manager.get_prediction_session
clear_prediction_session = manager.clear_prediction_session

# Recipe Sessions
set_recipe_session = manager.set_recipe_session
get_recipe_session = manager.get_recipe_session
clear_recipe_session = manager.clear_recipe_session

# Playlist Sessions
set_playlist_session = manager.set_playlist_session
get_playlist_session = manager.get_playlist_session
clear_playlist_session = manager.clear_playlist_session

# Translate Sessions
set_translate_session = manager.set_translate_session
get_translate_session = manager.get_translate_session
clear_translate_session = manager.clear_translate_session

# Translate Results
set_translate_result = manager.set_translate_result
get_translate_result = manager.get_translate_result
clear_translate_result = manager.clear_translate_result

# Wallapop Sessions
set_wallapop_session = manager.set_wallapop_session
get_wallapop_session = manager.get_wallapop_session
clear_wallapop_session = manager.clear_wallapop_session

# Wallapop Result Sessions
set_wallapop_result_session = manager.set_wallapop_result_session
get_wallapop_result_session = manager.get_wallapop_result_session
clear_wallapop_result_session = manager.clear_wallapop_result_session

# Wallapop Item Messages
set_wallapop_item_message = manager.set_wallapop_item_message
get_wallapop_item_message = manager.get_wallapop_item_message
clear_wallapop_item_message = manager.clear_wallapop_item_message

# Wallapop Alert Sessions
set_wallapop_alert_session = manager.set_wallapop_alert_session
get_wallapop_alert_session = manager.get_wallapop_alert_session
clear_wallapop_alert_session = manager.clear_wallapop_alert_session

# Reminder Sessions
set_reminder_session = manager.set_reminder_session
get_reminder_session = manager.get_reminder_session
clear_reminder_session = manager.clear_reminder_session

# Jellyfin Item Messages
set_jellyfin_item_message = manager.set_jellyfin_item_message
get_jellyfin_item_message = manager.get_jellyfin_item_message
clear_jellyfin_item_message = manager.clear_jellyfin_item_message

# Base cleanup functions
clear_base_chat_state = manager.clear_base_chat_state
clear_all_chat_state = manager.clear_all_chat_state

# Last message tracking
set_last_message_id = manager.set_last_message_id
get_last_message_id = manager.get_last_message_id

