from datetime import datetime

from extensions import db


ID_TYPES = ("nida", "driving_licence", "voter_id", "passport", "other")


class Borrower(db.Model):
    __tablename__ = "borrowers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    id_type = db.Column(db.String(20), nullable=False, default="nida")
    id_number = db.Column(db.String(80), nullable=False, index=True)
    id_verified = db.Column(db.Boolean, nullable=False, default=False)
    id_verified_at = db.Column(db.DateTime, nullable=True)
    id_verification_source = db.Column(db.String(80), nullable=True)
    address = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)  # legacy; uploads use photo_path
    # Uploaded files live under UPLOAD_DIR; only the generated file name is stored.
    photo_path = db.Column(db.String(255), nullable=True)
    id_document_path = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("id_type", "id_number", name="uq_borrowers_id_type_number"),
        db.CheckConstraint(
            "id_type IN ('nida', 'driving_licence', 'voter_id', 'passport', 'other')",
            name="ck_borrowers_id_type",
        ),
    )

    loans = db.relationship("Loan", back_populates="borrower", lazy=True)
