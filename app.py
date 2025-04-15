from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    is_admin = db.Column(db.Boolean, default=False)
    last_bonus = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/')
def index():
    if current_user.is_authenticated:
        users = User.query.all()
        return render_template('index.html', users=users)
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        
        flash('Geçersiz kullanıcı adı veya şifre')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/update_balance', methods=['POST'])
@login_required
def update_balance():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    
    user_id = request.form['user_id']
    new_balance = float(request.form['balance'])
    user = User.query.get(int(user_id))
    
    if user:
        user.balance = new_balance
        db.session.commit()
    
    return redirect(url_for('index'))

def create_admin():
    admin = User.query.filter_by(username='admincontrol').first()
    if not admin:
        admin = User(username='admincontrol', is_admin=True)
        admin.set_password('kontrolpaneli')
        db.session.add(admin)
        db.session.commit()

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok.')
        return redirect(url_for('index'))
    users = User.query.all()
    return render_template('admin.html', users=users)

@app.route('/admin/add_user', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Bu işlem için yetkiniz yok.')
        return redirect(url_for('index'))
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    if User.query.filter_by(username=username).first():
        flash('Bu kullanıcı adı zaten kullanılıyor.')
        return redirect(url_for('admin_panel'))
    
    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    flash('Kullanıcı başarıyla eklendi.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Bu işlem için yetkiniz yok.')
        return redirect(url_for('index'))
    
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('Admin kullanıcısı silinemez.')
        return redirect(url_for('admin_panel'))
    
    db.session.delete(user)
    db.session.commit()
    flash('Kullanıcı başarıyla silindi.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/edit_user/<int:user_id>', methods=['POST'])
@login_required
def edit_user(user_id):
    if not current_user.is_admin:
        flash('Bu işlem için yetkiniz yok.')
        return redirect(url_for('index'))
    
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password')
    
    if new_password:
        user.set_password(new_password)
        db.session.commit()
        flash('Kullanıcı şifresi güncellendi.')
    
    return redirect(url_for('admin_panel'))

def give_weekly_bonus():
    with app.app_context():
        users = User.query.all()
        current_time = datetime.utcnow()
        for user in users:
            if user.last_bonus is None or (current_time - user.last_bonus) >= timedelta(days=7):
                user.balance += 20.0
                user.last_bonus = current_time
        db.session.commit()

@app.route('/transfer', methods=['POST'])
@login_required
def transfer_money():
    recipient_username = request.form.get('recipient')
    amount = float(request.form.get('amount', 0))
    
    if amount <= 0:
        flash('Geçersiz transfer miktarı.')
        return redirect(url_for('index'))
    
    if current_user.balance < amount:
        flash('Yetersiz bakiye.')
        return redirect(url_for('index'))
    
    recipient = User.query.filter_by(username=recipient_username).first()
    if not recipient:
        flash('Alıcı bulunamadı.')
        return redirect(url_for('index'))
    
    if recipient.username == current_user.username:
        flash('Kendinize para transferi yapamazsınız.')
        return redirect(url_for('index'))
    
    current_user.balance -= amount
    recipient.balance += amount
    db.session.commit()
    
    flash(f'{amount} DIZ başarıyla {recipient_username} kullanıcısına transfer edildi.')
    return redirect(url_for('index'))

# API endpoints for mobile app
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    user = User.query.filter_by(username=data.get('username')).first()
    if user and user.check_password(data.get('password')):
        return jsonify({
            'status': 'success',
            'user_id': user.id,
            'username': user.username,
            'balance': user.balance,
            'is_admin': user.is_admin
        })
    return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    data = request.get_json()
    sender = User.query.get(data.get('user_id'))
    if not sender:
        return jsonify({'status': 'error', 'message': 'Sender not found'}), 404
    
    recipient = User.query.filter_by(username=data.get('recipient')).first()
    if not recipient:
        return jsonify({'status': 'error', 'message': 'Recipient not found'}), 404
    
    amount = float(data.get('amount', 0))
    if amount <= 0:
        return jsonify({'status': 'error', 'message': 'Invalid amount'}), 400
    
    if sender.balance < amount:
        return jsonify({'status': 'error', 'message': 'Insufficient balance'}), 400
    
    if sender.username == recipient.username:
        return jsonify({'status': 'error', 'message': 'Cannot transfer to yourself'}), 400
    
    sender.balance -= amount
    recipient.balance += amount
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'message': f'Successfully transferred {amount} DIZ to {recipient.username}',
        'new_balance': sender.balance
    })

@app.route('/api/balance/<int:user_id>', methods=['GET'])
def api_get_balance(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    return jsonify({
        'status': 'success',
        'balance': user.balance
    })

def init_db():
    with app.app_context():
        db.drop_all()  # Tüm tabloları sil
        db.create_all()  # Tabloları yeniden oluştur
        create_admin()   # Admin kullanıcısını oluştur

if __name__ == '__main__':
    init_db()  # Veritabanını başlangıçta oluştur
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=give_weekly_bonus, trigger="interval", days=7)
    scheduler.start()
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    is_admin = db.Column(db.Boolean, default=False)
    last_bonus = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/')
def index():
    if current_user.is_authenticated:
        users = User.query.all()
        return render_template('index.html', users=users)
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        
        flash('Geçersiz kullanıcı adı veya şifre')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/update_balance', methods=['POST'])
@login_required
def update_balance():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    
    user_id = request.form['user_id']
    new_balance = float(request.form['balance'])
    user = User.query.get(int(user_id))
    
    if user:
        user.balance = new_balance
        db.session.commit()
    
    return redirect(url_for('index'))

def create_admin():
    admin = User.query.filter_by(username='admincontrol').first()
    if not admin:
        admin = User(username='admincontrol', is_admin=True)
        admin.set_password('kontrolpaneli')
        db.session.add(admin)
        db.session.commit()

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok.')
        return redirect(url_for('index'))
    users = User.query.all()
    return render_template('admin.html', users=users)

@app.route('/admin/add_user', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Bu işlem için yetkiniz yok.')
        return redirect(url_for('index'))
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    if User.query.filter_by(username=username).first():
        flash('Bu kullanıcı adı zaten kullanılıyor.')
        return redirect(url_for('admin_panel'))
    
    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    flash('Kullanıcı başarıyla eklendi.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Bu işlem için yetkiniz yok.')
        return redirect(url_for('index'))
    
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('Admin kullanıcısı silinemez.')
        return redirect(url_for('admin_panel'))
    
    db.session.delete(user)
    db.session.commit()
    flash('Kullanıcı başarıyla silindi.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/edit_user/<int:user_id>', methods=['POST'])
@login_required
def edit_user(user_id):
    if not current_user.is_admin:
        flash('Bu işlem için yetkiniz yok.')
        return redirect(url_for('index'))
    
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password')
    
    if new_password:
        user.set_password(new_password)
        db.session.commit()
        flash('Kullanıcı şifresi güncellendi.')
    
    return redirect(url_for('admin_panel'))

def give_weekly_bonus():
    with app.app_context():
        users = User.query.all()
        current_time = datetime.utcnow()
        for user in users:
            if user.last_bonus is None or (current_time - user.last_bonus) >= timedelta(days=7):
                user.balance += 20.0
                user.last_bonus = current_time
        db.session.commit()

@app.route('/transfer', methods=['POST'])
@login_required
def transfer_money():
    recipient_username = request.form.get('recipient')
    amount = float(request.form.get('amount', 0))
    
    if amount <= 0:
        flash('Geçersiz transfer miktarı.')
        return redirect(url_for('index'))
    
    if current_user.balance < amount:
        flash('Yetersiz bakiye.')
        return redirect(url_for('index'))
    
    recipient = User.query.filter_by(username=recipient_username).first()
    if not recipient:
        flash('Alıcı bulunamadı.')
        return redirect(url_for('index'))
    
    if recipient.username == current_user.username:
        flash('Kendinize para transferi yapamazsınız.')
        return redirect(url_for('index'))
    
    current_user.balance -= amount
    recipient.balance += amount
    db.session.commit()
    
    flash(f'{amount} DIZ başarıyla {recipient_username} kullanıcısına transfer edildi.')
    return redirect(url_for('index'))

# API endpoints for mobile app
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    user = User.query.filter_by(username=data.get('username')).first()
    if user and user.check_password(data.get('password')):
        return jsonify({
            'status': 'success',
            'user_id': user.id,
            'username': user.username,
            'balance': user.balance,
            'is_admin': user.is_admin
        })
    return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    data = request.get_json()
    sender = User.query.get(data.get('user_id'))
    if not sender:
        return jsonify({'status': 'error', 'message': 'Sender not found'}), 404
    
    recipient = User.query.filter_by(username=data.get('recipient')).first()
    if not recipient:
        return jsonify({'status': 'error', 'message': 'Recipient not found'}), 404
    
    amount = float(data.get('amount', 0))
    if amount <= 0:
        return jsonify({'status': 'error', 'message': 'Invalid amount'}), 400
    
    if sender.balance < amount:
        return jsonify({'status': 'error', 'message': 'Insufficient balance'}), 400
    
    if sender.username == recipient.username:
        return jsonify({'status': 'error', 'message': 'Cannot transfer to yourself'}), 400
    
    sender.balance -= amount
    recipient.balance += amount
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'message': f'Successfully transferred {amount} DIZ to {recipient.username}',
        'new_balance': sender.balance
    })

@app.route('/api/balance/<int:user_id>', methods=['GET'])
def api_get_balance(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    return jsonify({
        'status': 'success',
        'balance': user.balance
    })

def init_db():
    with app.app_context():
        db.drop_all()  # Tüm tabloları sil
        db.create_all()  # Tabloları yeniden oluştur
        create_admin()   # Admin kullanıcısını oluştur

if __name__ == '__main__':
    init_db()  # Veritabanını başlangıçta oluştur
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=give_weekly_bonus, trigger="interval", days=7)
    scheduler.start()
    app.run(debug=True) 
