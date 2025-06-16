from flask import Flask, request, jsonify, render_template
from difflib import SequenceMatcher
import json
import os
import threading

# ---------- Configuration & Constants ----------
app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DATA_FILE = os.path.join(DATA_DIR, 'game_data.json')
PLAYER, BANKER, TIE = 'Player', 'Banker', 'Tie'
VALID_OUTCOMES = {PLAYER, BANKER, TIE}
VALID_CARDS = {'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'}
CARD_VALUES = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 0, 'J': 0, 'Q': 0, 'K': 0}
SIMILARITY_THRESHOLD = 0.8

# --- Thread-safe In-Memory Cache for Performance ---
game_data_cache = []
data_lock = threading.Lock()

def initialize_data():
    """Loads initial data from the file into the cache at startup."""
    global game_data_cache
    with data_lock:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                game_data_cache = data if isinstance(data, list) else []
            print(f"--- SUCCESS: Loaded {len(game_data_cache)} records from {DATA_FILE} ---")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            game_data_cache = []
            print(f"--- INFO: Could not load data file ({e}). Starting with an empty cache. ---")

# ---------- Utilities ----------
def save_data_to_file():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(game_data_cache, f, indent=2)
        return True
    except IOError as e:
        app.logger.error(f"Could not write to data file: {e}")
        return False

def fix_hand(hand_str: str) -> str | None:
    if not isinstance(hand_str, str): return None
    parts = [p.strip().upper() for p in hand_str.split('-')]
    if not all(p in VALID_CARDS for p in parts) or len(parts) not in [2, 3]: return None
    return '-'.join(parts)

def baccarat_total(hand_str: str) -> int:
    return sum(CARD_VALUES.get(card, 0) for card in hand_str.split('-')) % 10

def determine_outcome(player_total: int, banker_total: int) -> str:
    if player_total > banker_total: return PLAYER
    if banker_total > player_total: return BANKER
    return TIE

# ---------- Prediction Logic Functions ----------
def calculate_historical_prediction(user_sequence, all_historical_outcomes):
    seq_len = len(user_sequence)
    if len(all_historical_outcomes) <= seq_len:
        return {'error': 'Not enough historical data.'}
    match_results = [{'next_outcome': all_historical_outcomes[i + seq_len]} for i in range(len(all_historical_outcomes) - seq_len) if SequenceMatcher(None, user_sequence, all_historical_outcomes[i:i + seq_len]).ratio() >= SIMILARITY_THRESHOLD and all_historical_outcomes[i + seq_len] != TIE]
    if not match_results:
        pb_counts = {k: user_sequence.count(k) for k in (PLAYER, BANKER)}
        total = sum(pb_counts.values())
        if total == 0: return {'prediction': 'Banker', 'confidence': "0%", 'based_on': 'fallback_no_data'}
        prediction = max(pb_counts, key=pb_counts.get)
        confidence = round((pb_counts[prediction] / total) * 100, 2)
        return {'prediction': prediction, 'confidence': f"{confidence}%", 'based_on': 'fallback_logic'}
    outcome_counts = {k: [r['next_outcome'] for r in match_results].count(k) for k in (PLAYER, BANKER)}
    total_matches = sum(outcome_counts.values())
    if total_matches == 0: return {'error': 'Matches found, but all lead to a Tie.'}
    prediction = max(outcome_counts, key=outcome_counts.get)
    confidence = round((outcome_counts[prediction] / total_matches) * 100, 2)
    return {'prediction': prediction, 'confidence': f"{confidence}%", 'based_on': 'pattern_match', 'matches_found': len(match_results)}

def calculate_sequential_prediction(user_sequence):
    if len(user_sequence) < 2: return {'error': 'Sequence too short for this analysis.'}
    transitions = {PLAYER: {PLAYER: 0, BANKER: 0}, BANKER: {PLAYER: 0, BANKER: 0}}
    for i in range(len(user_sequence) - 1):
        current, next_val = user_sequence[i], user_sequence[i+1]
        if current in transitions and next_val in transitions[current]:
            transitions[current][next_val] += 1
    last_outcome = user_sequence[-1]
    if last_outcome not in transitions: return {'prediction': 'Banker', 'confidence': '0%', 'based_on': 'sequential_fallback', 'reason': 'Last round was a Tie.'}
    possible_outcomes = transitions[last_outcome]
    total_transitions = sum(possible_outcomes.values())
    if total_transitions == 0: return {'prediction': 'Banker', 'confidence': '0%', 'based_on': 'sequential_fallback', 'reason': f'No transitions from "{last_outcome}" found in sequence.'}
    prediction = max(possible_outcomes, key=possible_outcomes.get)
    confidence = round((possible_outcomes[prediction] / total_transitions) * 100, 2)
    return {'prediction': prediction, 'confidence': f"{confidence}%", 'based_on': 'transition_analysis'}

# ---------- Routes ----------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/add_game', methods=['POST'])
def add_game():
    data = request.get_json()
    if not data: return jsonify({'error': 'Invalid JSON payload'}), 400
    player_hand = fix_hand(data.get('player_hand'))
    banker_hand = fix_hand(data.get('banker_hand'))
    outcome = data.get('outcome')
    if not all([player_hand, banker_hand, outcome]): return jsonify({'error': 'All fields are required.'}), 400
    if determine_outcome(baccarat_total(player_hand), baccarat_total(banker_hand)) != outcome: return jsonify({'error': "Outcome does not match card totals."}), 400
    with data_lock:
        game_data_cache.append({'player_hand': player_hand, 'banker_hand': banker_hand, 'outcome': outcome})
        if not save_data_to_file():
            game_data_cache.pop()
            return jsonify({'error': 'Failed to save data to file.'}), 500
    return jsonify({'message': 'Game added successfully'}), 201

@app.route('/predict_sequence', methods=['POST'])
def predict_sequence():
    data = request.get_json()
    if not data: return jsonify({'error': 'Invalid JSON payload'}), 400
    user_sequence = data.get('outcomes', [])
    if not isinstance(user_sequence, list) or len(user_sequence) < 10: return jsonify({'error': 'Please provide at least 10 valid outcomes.'}), 400
    with data_lock:
        all_outcomes = [g['outcome'] for g in game_data_cache]
    return jsonify({
        'historical_prediction': calculate_historical_prediction(user_sequence, all_outcomes),
        'sequential_prediction': calculate_sequential_prediction(user_sequence)
    })

# ---------- Run App ----------
if __name__ == '__main__':
    initialize_data()
    port = int(os.environ.get('PORT', 5000))
app.run(host='0.0.0.0', port=port)
