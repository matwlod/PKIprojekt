import sqlite3
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'abcd'
socketio = SocketIO(app)

def connect_db():
    return sqlite3.connect('matches.db')

def init_db():
    with connect_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS MATCHES (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                Date TEXT NOT NULL,
                TeamA_Name TEXT NOT NULL,
                TeamB_Name TEXT NOT NULL,
                Result TEXT DEFAULT '0-0',
                DetailedResult TEXT DEFAULT '[]',
                Status TEXT DEFAULT 'PLANNED',
                StartDate TEXT,
                SetDate TEXT
            )
        ''')

init_db()

@app.route('/')
def index():
    status_filter = request.args.get('status')
    with connect_db() as conn:
        if status_filter:
            matches = conn.execute('SELECT * FROM MATCHES WHERE Status = ?', (status_filter,)).fetchall()
        else:
            matches = conn.execute('SELECT * FROM MATCHES').fetchall()
    return render_template('index.html', matches=matches)


@app.route('/copy_match/<int:match_id>', methods=['GET'])
def copy_match(match_id):
    with connect_db() as conn:
        match = conn.execute('SELECT * FROM MATCHES WHERE ID = ?', (match_id,)).fetchone()

    if not match:
        return "Match not found", 404

    detailed_result = json.loads(match[5])


    team_a_name = match[2]
    team_b_name = match[3]
    total_sets = match[4]
    date = match[1]

    table = "       S1   |  S2   |  S3   |  S4   |  S5   | Total \n"
    table += "-" * 50 + "\n"

    team_a_row = f"{team_a_name: <5} "
    team_b_row = f"{team_b_name: <5} "


    for i in range(5):
        if i < len(detailed_result):
            team_a_row += f"{detailed_result[i][0]: <5} | "
            team_b_row += f"{detailed_result[i][1]: <5} | "
        else:
            team_a_row += "     | "
            team_b_row += "     | "

    team_a_sets, team_b_sets = total_sets.split("-")
    team_a_row += f"{team_a_sets: <5}\n"
    team_b_row += f"{team_b_sets: <5}\n"

    table += team_a_row + team_b_row
    table += f"\nDate: {date}"

    return table


@app.route('/match/<int:match_id>')
def match_page(match_id):
    with connect_db() as conn:
        match = conn.execute('SELECT * FROM MATCHES WHERE ID = ?', (match_id,)).fetchone()
    if not match:
        return "Match not found", 404

    detailed_result = json.loads(match[5])
    current_set = detailed_result[-1] if detailed_result else [0, 0]
    sets_score = match[4]
    status = match[6]

    return render_template('match.html',
                           match_id=match[0],
                           team_a_name=match[2],
                           team_b_name=match[3],
                           sets_score=sets_score,
                           current_set=current_set,
                           status=status,
                           detailed_result=json.dumps(detailed_result))

# Add a new match
@app.route('/new_match', methods=['GET', 'POST'])
def new_match():
    if request.method == 'POST':
        team_a = request.form['team_a_name']
        team_b = request.form['team_b_name']
        date = request.form['match_date']

        with connect_db() as conn:
            conn.execute('''
                INSERT INTO MATCHES (Date, TeamA_Name, TeamB_Name, Status) 
                VALUES (?, ?, ?, 'PLANNED')
            ''', (date, team_a, team_b))
            conn.commit()
            match_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        socketio.emit('new_match', {'id': match_id, 'team_a_name': team_a, 'team_b_name': team_b, 'status': 'PLANNED',"Date":date})
        return redirect(url_for('index'))
    return render_template('new_match.html')


@socketio.on('remove_match')
def remove_match(data):
    match_id = int(data['match_id'])
    print("REMOVED")
    with connect_db() as conn:
        conn.execute('''
            DELETE FROM MATCHES
            WHERE ID = ?
        ''', (match_id,))
        conn.commit()

    socketio.emit('match_removed', {'match_id': match_id})


def finish_match(data):
    match_id = data
    with connect_db() as conn:
        conn.execute('''
            UPDATE MATCHES 
            SET Status = 'FINISHED'
            WHERE ID = ?
        ''', (match_id,))
        conn.commit()

@socketio.on('update_score')
def update_score(data):
    setFinish=0
    match_id = data['match_id']
    team = data['team']
    delta = data['delta']
    #print(match_id,team,delta)

    with connect_db() as conn:
        match = conn.execute('SELECT * FROM MATCHES WHERE ID = ?', (match_id,)).fetchone()
        detailed_result = json.loads(match[5])
        teamA=match[2]
        teamB=match[3]
        if not match[7] and delta ==1:
            conn.execute('''
                       UPDATE MATCHES 
                       SET StartDate = ?
                       WHERE ID = ?
                   ''', (datetime.now().isoformat(),match_id))
            conn.commit()
            startDate = datetime.now().isoformat()
        if not match[8] and delta ==1:
            conn.execute('''
                                   UPDATE MATCHES 
                                   SET SetDate = ?
                                   WHERE ID = ?
                               ''', (datetime.now().isoformat(), match_id))
            conn.commit()
            setDate = datetime.now().isoformat()

        result = match[4]
        matchStatus=match[6]
        if delta==3 or matchStatus=="FINISHED":
            print("finich")
            finish_match(match_id)
            socketio.emit('match_update', {
                'match_id': match_id,
                'teamA': teamA,
                "teamB": teamB,
                'detailed_result': json.dumps(detailed_result),
                'result': result,
                'status': "FINISHED",
                'finishable': 0,
                'finished': 1
            })
            return
        sets = result.split('-')
        team_a_sets = int(sets[0])
        team_b_sets = int(sets[1])
        setNumber=team_a_sets+team_b_sets+1
        if len(detailed_result) == 0:
            detailed_result.append([0, 0])

        current_set = detailed_result[-1]

        if delta==1 or delta==-1:
            if team == 'team_a':
                if current_set[0]==0 and delta==-1:
                    pass
                else:
                    current_set[0] += delta
            else:
                if current_set[1] == 0 and delta == -1:
                    pass
                else:
                    current_set[1] += delta

        if current_set[0] >= 25 and current_set[0] >= current_set[1] + 2 and setNumber != 5:
            setFinish=1
        elif current_set[1] >= 25 and current_set[1] >= current_set[0] + 2 and setNumber != 5:
            setFinish=1
        if current_set[0] >= 15 and current_set[0] >= current_set[1] + 2 and setNumber == 5:
            setFinish=1
        elif current_set[1] >= 15 and current_set[1] >= current_set[0] + 2 and setNumber == 5:
            setFinish=1

        swap=0
        finish = 0
        if match[7]:
            startDate=match[7]
        if match[8]:
            setDate=match[8]
        if delta==4:
            if current_set[0] >= 25 and current_set[0] >= current_set[1] + 2 and setNumber !=5:
                setDate=datetime.now().isoformat()
                team_a_sets += 1
                if team_a_sets >= 3:
                    finish = 1
                swap=1
                setFinish=0
                detailed_result.append([0, 0])
            elif current_set[1] >= 25 and current_set[1] >= current_set[0] + 2 and setNumber !=5:
                setDate = datetime.now().isoformat()
                team_b_sets += 1
                if team_b_sets >= 3:
                    finish = 1
                setFinish = 0
                swap = 1
                detailed_result.append([0, 0])
            if current_set[0] >= 15 and current_set[0] >= current_set[1] + 2 and setNumber ==5:
                setDate = datetime.now().isoformat()
                team_a_sets += 1
                if team_a_sets >=3:
                    finish = 1
                setFinish = 0
                finish=1
                detailed_result.append([0, 0])
            elif current_set[1] >= 15 and current_set[1] >= current_set[0] + 2 and setNumber ==5:
                setDate = datetime.now().isoformat()
                team_b_sets += 1
                finish = 1
                setFinish = 0
                detailed_result.append([0, 0])

        if setNumber == 5 and detailed_result[-1][0]+detailed_result[-1][1]==8:
            swap=1

        if team_b_sets == 3 or team_a_sets == 3:
            finish = 1

        new_result = f"{team_a_sets}-{team_b_sets}"
        if not match[7] and delta ==1:
            conn.execute('''
                       UPDATE MATCHES 
                       SET StartDate = ?
                       WHERE ID = ?
                   ''', (datetime.now().isoformat(),match_id))
            conn.commit()
            startDate = datetime.now().isoformat()
        if not match[8] and delta ==1:
            conn.execute('''
                                   UPDATE MATCHES 
                                   SET SetDate = ?
                                   WHERE ID = ?
                               ''', (datetime.now().isoformat(), match_id))
            conn.commit()
            setDate = datetime.now().isoformat()
        conn.execute('''
            UPDATE MATCHES 
            SET DetailedResult = ?, Result = ? , Status = "IN_PROGRESS" ,StartDate = ?,SetDate = ?
            WHERE ID = ?
        ''', (json.dumps(detailed_result), new_result,startDate,setDate, match_id))
        conn.commit()
        if len(detailed_result) > 1 and detailed_result[-1] == [0, 0]:
            current_set[0] = 0
            current_set[1] = 0
    status = "IN PROGRESS"
    finished = 0

    if matchStatus == "FINISHED":
        status="FINISHED"
        finished=1
    socketio.emit('match_update', {
        'match_id': match_id,
        'teamA':teamA,
        "teamB":teamB,
        'detailed_result': json.dumps(detailed_result),
        'result': new_result,
        'status': status,
        'finishable':finish,
        'finished':finished,
        'setFinish':setFinish,
        'startDate':startDate,
        "setDate":setDate
    })
    if swap:
        swap_teams(data)

@socketio.on('swap_teams')
def swap_teams(data):
    match_id = data['match_id']

    with connect_db() as conn:
        match = conn.execute('SELECT * FROM MATCHES WHERE ID = ?', (match_id,)).fetchone()
        team_a_name = match[2]
        team_b_name = match[3]
        status= match[6]
        result = match[4]
        detailed_result = json.loads(match[5])

        swapped_detailed_result = [[b, a] for a, b in detailed_result]
        swapped_result = "-".join(reversed(result.split('-')))

        conn.execute('''
            UPDATE MATCHES 
            SET TeamA_Name = ?, TeamB_Name = ?, Result = ?, DetailedResult = ?
            WHERE ID = ?
        ''', (team_b_name, team_a_name, swapped_result, json.dumps(swapped_detailed_result), match_id))
        conn.commit()
        print("SWAPPED")

    socketio.emit('match_update', {
        'match_id': match_id,
        'teamA':team_b_name,
        "teamB":team_a_name,
        'result': swapped_result,
        "status":status,
        'detailed_result': json.dumps(swapped_detailed_result)
    })

if __name__ == '__main__':
    socketio.run(app, debug=True)
