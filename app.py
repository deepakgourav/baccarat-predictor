from flask import Flask, request, jsonify, render_template
from difflib import SequenceMatcher
import json
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'data', 'game_data.json')

# ---------- Utilities ----------
def create_initial_data():
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w') as f:
            json.dump([], f, indent=2)

def fix_hand(hand_str):
    valid_cards = {'A','2','3','4','5','6','7','8','9','10','J','Q','K'}
    hand_str = str(hand_str).replace('-', '')
    cards = []
    i = 0
    while i < len(hand_str):
        if hand_str[i] == '1' and i+1 < len(hand_str) and hand_str[i+1] == '0':
            cards.append('10')
            i += 2
        else:
            cards.append(hand_str[i])
            i += 1
    return '-'.join(card for card in cards if card in valid_cards)

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except:
        return []

def save_data(data):
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except:
        return False

# ---------- Baccarat Logic ----------
card_values = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5,
               '6': 6, '7': 7, '8': 8, '9': 9,
               '10': 0, 'J': 0, 'Q': 0, 'K': 0}

def baccarat_total(hand_str):
    try:
        cards = hand_str.split('-')
        return sum(card_values.get(card, 0) for card in cards) % 10
    except:
        return 0

def determine_outcome(player_total, banker_total):
    if player_total > banker_total:
        return 'Player'
    elif banker_total > player_total:
        return 'Banker'
    else:
        return 'Tie'

# ---------- Routes ----------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/add_game', methods=['POST'])
def add_game():
    try:
        data = request.get_json()
        player_hand = fix_hand(data.get('player_hand', ''))
        banker_hand = fix_hand(data.get('banker_hand', ''))
        outcome = data.get('outcome', '')

        if not all([player_hand, banker_hand, outcome]):
            return jsonify({'error': 'All fields are required'}), 400

        if outcome not in ['Player', 'Banker', 'Tie']:
            return jsonify({'error': 'Invalid outcome'}), 400

        player_total = baccarat_total(player_hand)
        banker_total = baccarat_total(banker_hand)
        predicted = determine_outcome(player_total, banker_total)

        if predicted != outcome:
            return jsonify({'error': f"Outcome does not match card totals. Calculated: {predicted}"}), 400

        games = load_data()
        games.append({
            'player_hand': player_hand,
            'banker_hand': banker_hand,
            'outcome': outcome
        })

        if not save_data(games):
            return jsonify({'error': 'Failed to save data'}), 500

        return jsonify({'message': 'Game added successfully'}), 201
    except Exception as e:
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

@app.route('/predict_sequence', methods=['POST'])
def predict_sequence():
    try:
        data = request.get_json()
        sequence = data.get('sequence', [])

        if len(sequence) < 10 or any(o not in ["Player", "Banker"] for o in sequence):
            return jsonify({'error': 'Provide at least 10 valid outcomes: "Player" or "Banker"'}), 400

        # Use last 10 rounds for prediction
        user_sequence = sequence[-10:]

        historical_data = load_data()
        all_outcomes = [g['outcome'] for g in historical_data if g['outcome'] in ['Player', 'Banker']]

        # Exact/Fuzzy match logic
        match_results = []
        for i in range(len(all_outcomes) - 10):
            window = all_outcomes[i:i+10]
            next_outcome = all_outcomes[i+10] if i + 10 < len(all_outcomes) else None
            if not next_outcome:
                continue
            exact_match = user_sequence == window
            fuzzy_match_ratio = SequenceMatcher(None, user_sequence, window).ratio()
            if exact_match or fuzzy_match_ratio >= 0.8:
                match_results.append({
                    'start_index': i,
                    'matched_sequence': window,
                    'next_outcome': next_outcome,
                    'match_type': 'exact' if exact_match else 'fuzzy',
                    'similarity': round(fuzzy_match_ratio * 100, 2)
                })

        predictions = []

        if match_results:
            outcome_counts = {'Player': 0, 'Banker': 0}
            for match in match_results:
                outcome_counts[match['next_outcome']] += 1

            total = outcome_counts['Player'] + outcome_counts['Banker']
            predicted = max(outcome_counts, key=outcome_counts.get)
            confidence = round((outcome_counts[predicted] / total) * 100, 2)
            predictions.append({
                'prediction': predicted,
                'confidence': f"{confidence}%",
                'based_on': 'pattern_match',
                'matches_found': len(match_results)
            })

        # Partial match fallback logic
        partial_match_counts = {'Player': 0, 'Banker': 0}
        for i in range(len(all_outcomes) - 10):
            window = all_outcomes[i:i+10]
            next_outcome = all_outcomes[i+10]
            fuzzy_match_ratio = SequenceMatcher(None, user_sequence, window).ratio()
            if fuzzy_match_ratio >= 0.5:
                partial_match_counts[next_outcome] += 1

        total_partial = partial_match_counts['Player'] + partial_match_counts['Banker']
        if total_partial > 0:
            predicted = max(partial_match_counts, key=partial_match_counts.get)
            confidence = round((partial_match_counts[predicted] / total_partial) * 100, 2)
            predictions.append({
                'prediction': predicted,
                'confidence': f"{confidence}%",
                'based_on': 'partial_match_fallback'
            })

        # Final fallback if no historical data at all
        if not predictions:
            fallback_counts = {'Player': user_sequence.count('Player'), 'Banker': user_sequence.count('Banker')}
            fallback_pred = max(fallback_counts, key=fallback_counts.get)
            fallback_conf = round((fallback_counts[fallback_pred] / 10) * 100, 2)
            predictions.append({
                'prediction': fallback_pred,
                'confidence': f"{fallback_conf}%",
                'based_on': 'final_fallback',
                'reason': 'no historical pattern found'
            })

        return jsonify({
            'predictions': predictions
        })
    except Exception as e:
        return jsonify({'error': 'Prediction failed', 'details': str(e)}), 500

# ---------- Run App ----------
if __name__ == '__main__':
    create_initial_data()
    app.run(host='0.0.0.0', port=3000, debug=True)
