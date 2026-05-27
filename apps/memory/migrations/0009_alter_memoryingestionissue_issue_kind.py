from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("memory", "0008_remove_memoryclaim_created_by_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memoryingestionissue",
            name="issue_kind",
            field=models.CharField(
                choices=[
                    ("encrypted_file", "Encrypted file"),
                    ("unsupported_format", "Unsupported format"),
                    ("file_too_large", "File too large"),
                    ("partial_indexed", "Partial indexed"),
                    ("parser_timeout", "Parser timeout"),
                    ("ocr_timeout", "OCR timeout"),
                    ("pii_blocked", "PII blocked"),
                    ("pii_audit", "PII audit"),
                    ("secret_blocked", "Secret blocked"),
                    ("acl_unresolved", "ACL unresolved"),
                    ("schema_unknown_type", "Schema unknown type"),
                    ("schema_unknown_relation", "Schema unknown relation"),
                    ("canonicalization_conflict", "Canonicalization conflict"),
                ],
                max_length=64,
            ),
        ),
    ]
