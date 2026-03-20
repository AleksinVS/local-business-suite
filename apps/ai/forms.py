from django import forms


class AIChatInputForm(forms.Form):
    prompt = forms.CharField(
        label="Сообщение",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Например: покажи новые заявки или создай заявку на светильник в поликлинике",
            }
        ),
    )
