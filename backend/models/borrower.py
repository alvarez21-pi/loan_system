from datetime import datetime

from extensions import db


class Borrower(db.Model):
    __tablename__ = "borrowers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    id_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    address = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    loans = db.relationship("Loan", back_populates="borrower", lazy=True)
