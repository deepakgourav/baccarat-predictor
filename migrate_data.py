import json
import os
import shutil

# --- Configuration ---
DATA_FILE = os.path.join('data', 'game_data.json')
BACKUP_FILE = os.path.join('data', 'game_data.json.bak')
ROUNDS_PER_SHOE = 85

def migrate_to_flat_list_with_markers():
    """
    Reads game_data.json, creates a backup, and overwrites the original
    file with a flat list that includes 'SHOE_START' and 'SHOE_END' markers.
    """
    print("--- Starting Data Migration (with Shoe Markers) ---")

    if not os.path.exists(DATA_FILE):
        print(f"❌ Error: The file '{DATA_FILE}' was not found.")
        return

    try:
        shutil.copyfile(DATA_FILE, BACKUP_FILE)
        print(f"✅ Success: Backup created at '{BACKUP_FILE}'")
    except Exception as e:
        print(f"❌ Error: Could not create backup. Aborting. {e}")
        return

    try:
        with open(DATA_FILE, 'r') as f:
            old_data = json.load(f)
        print(f"✅ Success: Loaded {len(old_data)} total rounds.")
    except Exception as e:
        print(f"❌ Error: Could not read or parse the data file. {e}")
        return

    # This handles if the data is already a list OR the {"shoes": []} format
    if isinstance(old_data, dict) and 'shoes' in old_data:
        flat_list = []
        for shoe in old_data.get('shoes', []):
            for outcome in shoe.get('outcomes', []):
                flat_list.append(outcome)
        old_data = flat_list
    elif not isinstance(old_data, list):
        print("❌ Error: Data is not in a recognized list format.")
        return

    # This will be our new, flat list with markers
    new_flat_list_with_markers = []
    shoe_counter = 1
    
    print("\nProcessing rounds and adding shoe markers...")
    for i in range(0, len(old_data), ROUNDS_PER_SHOE):
        shoe_rounds_data = old_data[i:i + ROUNDS_PER_SHOE]
        
        if len(shoe_rounds_data) < 10:
            print(f"Skipping final chunk of {len(shoe_rounds_data)} rounds (too small).")
            continue
            
        current_shoe_id = f"shoe_{shoe_counter}"
        
        # --- Add the START marker ---
        new_flat_list_with_markers.append({
            "event": "SHOE_START",
            "shoe_id": current_shoe_id
        })
        
        for round_index, round_data in enumerate(shoe_rounds_data):
            # This logic handles both old strings and new dictionaries
            new_round_object = {}
            if isinstance(round_data, dict):
                new_round_object = round_data
            else:
                outcome_map = {'P': 'Player', 'B': 'Banker', 'T': 'Tie'}
                full_outcome = outcome_map.get(str(round_data), str(round_data))
                new_round_object = {"outcome": full_outcome, "player_hand": "N/A", "banker_hand": "N/A"}

            new_round_object['shoe_id'] = current_shoe_id
            new_round_object['round'] = round_index + 1
            new_flat_list_with_markers.append(new_round_object)

        # --- Add the END marker ---
        new_flat_list_with_markers.append({
            "event": "SHOE_END",
            "shoe_id": current_shoe_id
        })
        
        print(f"Added markers and {len(shoe_rounds_data)} rounds for '{current_shoe_id}'.")
        shoe_counter += 1

    # --- Overwrite the original file with the new flat list ---
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(new_flat_list_with_markers, f, indent=2)
        print(f"\n🎉 Migration Complete! 🎉")
        print(f"✅ Success: Your '{DATA_FILE}' now includes shoe start/end markers.")
    except Exception as e:
        print(f"❌ Error: Could not write the new data to '{DATA_FILE}'. {e}")

if __name__ == '__main__':
    migrate_to_flat_list_with_markers()