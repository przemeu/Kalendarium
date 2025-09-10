"""
Email utilities for sending authentication emails
"""
from flask_mail import Message
from flask import url_for, current_app

def send_confirmation_email(mail, email, token):
    """Send email confirmation message"""
    try:
        subject = "Confirm Your Arka Kalendarium Account"
        
        confirmation_url = url_for('confirm_email', token=token, _external=True)
        
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="text-align: center; margin-bottom: 30px;">
                <img src="https://arka.gdynia.pl/files/herb/arka_gdynia_mzks_kolor.png" alt="Arka Gdynia" style="max-width: 100px;">
                <h1 style="color: #d4a017; margin: 20px 0;">Arka Kalendarium</h1>
            </div>
            
            <div style="background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h2 style="color: #333; margin-bottom: 20px;">Welcome to Arka Kalendarium!</h2>
                
                <p style="font-size: 16px; line-height: 1.6; color: #555; margin-bottom: 20px;">
                    Thank you for registering an account. Please click the button below to confirm your email address and activate your account.
                </p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{confirmation_url}" 
                       style="display: inline-block; padding: 15px 30px; background: linear-gradient(90deg, #f5c000, #d4a017); 
                              color: white; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px;">
                        Confirm Email Address
                    </a>
                </div>
                
                <div style="background: #f8f9fa; padding: 15px; border-radius: 6px; margin: 20px 0; border-left: 4px solid #d4a017;">
                    <p style="margin: 0; color: #666; font-size: 14px;">
                        <strong>Security Note:</strong> This confirmation link will expire in 1 hour for your security.
                    </p>
                </div>
                
                <p style="font-size: 14px; color: #666; margin-top: 30px;">
                    If you didn't create an account, please ignore this email.
                </p>
                
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                
                <div style="text-align: center; color: #999; font-size: 12px;">
                    <p>Arka Kalendarium - Football Match Statistics</p>
                    <p>This is an automated message, please do not reply.</p>
                </div>
            </div>
        </div>
        """
        
        text_body = f"""
        Welcome to Arka Kalendarium!
        
        Thank you for registering an account. Please visit the following link to confirm your email address:
        
        {confirmation_url}
        
        This confirmation link will expire in 1 hour for your security.
        
        If you didn't create an account, please ignore this email.
        
        ---
        Arka Kalendarium - Football Match Statistics
        """
        
        msg = Message(
            subject=subject,
            recipients=[email],
            html=html_body,
            body=text_body
        )
        
        mail.send(msg)
        return True, "Email sent successfully"
        
    except Exception as e:
        current_app.logger.error(f"Failed to send confirmation email to {email}: {str(e)}")
        return False, f"Failed to send email: {str(e)}"

def send_welcome_email(mail, email):
    """Send welcome email after successful confirmation"""
    try:
        subject = "Welcome to Arka Kalendarium!"
        
        html_body = """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="text-align: center; margin-bottom: 30px;">
                <img src="https://arka.gdynia.pl/files/herb/arka_gdynia_mzks_kolor.png" alt="Arka Gdynia" style="max-width: 100px;">
                <h1 style="color: #d4a017; margin: 20px 0;">Arka Kalendarium</h1>
            </div>
            
            <div style="background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h2 style="color: #333; margin-bottom: 20px;">🎉 Account Confirmed!</h2>
                
                <p style="font-size: 16px; line-height: 1.6; color: #555; margin-bottom: 20px;">
                    Your email has been successfully confirmed. You can now access all features of the Arka Kalendarium including:
                </p>
                
                <ul style="color: #555; line-height: 1.8; margin-bottom: 25px;">
                    <li>📊 Detailed match statistics and analysis</li>
                    <li>🔍 Advanced filtering and search capabilities</li>
                    <li>📈 Historical performance tracking</li>
                    <li>📋 Export data to Excel</li>
                    <li>⚽ Goal scorer and lineup information</li>
                </ul>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="http://127.0.0.1:5000/" 
                       style="display: inline-block; padding: 15px 30px; background: linear-gradient(90deg, #f5c000, #d4a017); 
                              color: white; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px;">
                        Start Exploring
                    </a>
                </div>
                
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                
                <div style="text-align: center; color: #999; font-size: 12px;">
                    <p>Arka Kalendarium - Football Match Statistics</p>
                    <p>Tracking Arka Gdynia matches since 1929</p>
                </div>
            </div>
        </div>
        """
        
        text_body = """
        Account Confirmed!
        
        Your email has been successfully confirmed. You can now access all features of the Arka Kalendarium.
        
        Visit: http://127.0.0.1:5000/
        
        ---
        Arka Kalendarium - Football Match Statistics
        """
        
        msg = Message(
            subject=subject,
            recipients=[email],
            html=html_body,
            body=text_body
        )
        
        mail.send(msg)
        return True, "Welcome email sent"
        
    except Exception as e:
        current_app.logger.error(f"Failed to send welcome email to {email}: {str(e)}")
        return False, f"Failed to send email: {str(e)}"