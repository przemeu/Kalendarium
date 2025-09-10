"""
Authentication utilities for secure user management
"""
import bcrypt
import sqlite3
import os
from datetime import datetime, timedelta
from itsdangerous import URLSafeTimedSerializer, BadSignature
import re
from email_validator import validate_email, EmailNotValidError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'Kalendarium.db')

class AuthManager:
    def __init__(self, secret_key, salt='user-auth'):
        self.secret_key = secret_key
        self.salt = salt
        self.serializer = URLSafeTimedSerializer(secret_key)
    
    def hash_password(self, password):
        """Hash a password with bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')
    
    def verify_password(self, password, hashed):
        """Verify a password against its hash"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    def validate_password_strength(self, password):
        """Validate password meets security requirements"""
        errors = []
        
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long")
        if not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter")
        if not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter")
        if not re.search(r'\d', password):
            errors.append("Password must contain at least one digit")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append("Password must contain at least one special character")
        
        return errors
    
    def validate_email_format(self, email):
        """Validate email format"""
        try:
            validate_email(email)
            return True, None
        except EmailNotValidError as e:
            return False, str(e)
    
    def generate_confirmation_token(self, email):
        """Generate email confirmation token"""
        return self.serializer.dumps(email, salt=self.salt)
    
    def confirm_token(self, token, expiration=3600):
        """Verify confirmation token (1 hour default expiration)"""
        try:
            email = self.serializer.loads(
                token,
                salt=self.salt,
                max_age=expiration
            )
            return email
        except BadSignature:
            return None
    
    def get_db_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    
    def create_user(self, email, password):
        """Create new user account"""
        # Validate inputs
        email_valid, email_error = self.validate_email_format(email)
        if not email_valid:
            return False, f"Invalid email: {email_error}"
        
        password_errors = self.validate_password_strength(password)
        if password_errors:
            return False, "; ".join(password_errors)
        
        # Check if user already exists
        conn = self.get_db_connection()
        try:
            existing_user = conn.execute(
                'SELECT id FROM users WHERE email = ?', (email.lower(),)
            ).fetchone()
            
            if existing_user:
                return False, "Email already registered"
            
            # Hash password and generate confirmation token
            password_hash = self.hash_password(password)
            confirmation_token = self.generate_confirmation_token(email)
            
            # Insert new user
            conn.execute('''
                INSERT INTO users (email, password_hash, confirmation_token, created_at)
                VALUES (?, ?, ?, ?)
            ''', (email.lower(), password_hash, confirmation_token, datetime.utcnow()))
            
            conn.commit()
            return True, confirmation_token
            
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()
    
    def authenticate_user(self, email, password):
        """Authenticate user login"""
        conn = self.get_db_connection()
        try:
            user = conn.execute('''
                SELECT id, email, password_hash, is_confirmed, failed_login_attempts, locked_until
                FROM users WHERE email = ?
            ''', (email.lower(),)).fetchone()
            
            if not user:
                return None, "Invalid email or password"
            
            # Check if account is locked
            if user['locked_until'] and datetime.utcnow() < datetime.fromisoformat(user['locked_until']):
                return None, "Account temporarily locked due to too many failed attempts"
            
            # Check if account is confirmed
            if not user['is_confirmed']:
                return None, "Please confirm your email address before logging in"
            
            # Verify password
            if self.verify_password(password, user['password_hash']):
                # Reset failed attempts and update last login
                conn.execute('''
                    UPDATE users SET failed_login_attempts = 0, locked_until = NULL, last_login = ?
                    WHERE id = ?
                ''', (datetime.utcnow(), user['id']))
                conn.commit()
                
                return dict(user), None
            else:
                # Increment failed attempts
                failed_attempts = user['failed_login_attempts'] + 1
                locked_until = None
                
                if failed_attempts >= 5:
                    # Lock account for 15 minutes
                    locked_until = datetime.utcnow() + timedelta(minutes=15)
                
                conn.execute('''
                    UPDATE users SET failed_login_attempts = ?, locked_until = ?
                    WHERE id = ?
                ''', (failed_attempts, locked_until, user['id']))
                conn.commit()
                
                return None, "Invalid email or password"
                
        except sqlite3.Error as e:
            return None, f"Database error: {e}"
        finally:
            conn.close()
    
    def confirm_email(self, token):
        """Confirm user email with token"""
        email = self.confirm_token(token)
        if not email:
            return False, "Invalid or expired confirmation token"
        
        conn = self.get_db_connection()
        try:
            result = conn.execute('''
                UPDATE users SET is_confirmed = TRUE, confirmation_token = NULL
                WHERE email = ? AND is_confirmed = FALSE
            ''', (email.lower(),))
            
            if result.rowcount == 0:
                return False, "Email already confirmed or user not found"
            
            conn.commit()
            return True, "Email confirmed successfully"
            
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()
    
    def get_user_by_id(self, user_id):
        """Get user by ID"""
        conn = self.get_db_connection()
        try:
            user = conn.execute(
                'SELECT id, email, is_confirmed, created_at, last_login FROM users WHERE id = ?',
                (user_id,)
            ).fetchone()
            return dict(user) if user else None
        except sqlite3.Error:
            return None
        finally:
            conn.close()
    
    def resend_confirmation(self, email):
        """Resend confirmation email"""
        conn = self.get_db_connection()
        try:
            user = conn.execute('''
                SELECT id, is_confirmed FROM users WHERE email = ?
            ''', (email.lower(),)).fetchone()
            
            if not user:
                return False, "Email not found"
            
            if user['is_confirmed']:
                return False, "Email already confirmed"
            
            # Generate new token
            new_token = self.generate_confirmation_token(email)
            
            conn.execute('''
                UPDATE users SET confirmation_token = ? WHERE email = ?
            ''', (new_token, email.lower()))
            conn.commit()
            
            return True, new_token
            
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()