# Ganatleba Builder MVP

ეს ვერსია აკეთებს შემდეგს:

- ქართული ინტერფეისი
- PostgreSQL მხარდაჭერა
- ავტორიზაცია და რეგისტრაცია
- კურსის კონსტრუქტორი მომხმარებლისთვის
- თავები და გაკვეთილები
- ცალკე გვერდები თითოეული გაკვეთილისთვის
- გაკვეთილის ტიპები:
  - ტექსტი / დოკუმენტაცია / ვიდეო
  - ტესტი checkbox-ებით და სწორი პასუხებით
  - Python კოდის ამოცანა ტესტ-ქეისებით
  - შესაბამისობის დავალება
- გაკვეთილის პროგრესი მარცხენა პანელში
- გაკვეთილებისა და კურსების ლაიქი / დისლაიქი
- კომენტარები, პასუხები, კომენტარის ლაიქი / დისლაიქი
- ადმინის პანელი

## გაშვება

```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

## PostgreSQL

`.env` ფაილში მიუთითე შენი სწორი `DATABASE_URL`.

მაგალითი:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/edu_platform_ge
```

## უსაფრთხოების შენიშვნა

Python კოდის შემოწმება ამ MVP-ში კეთდება ლოკალური subprocess-ით. ეს **მისაღებია მხოლოდ ლოკალური დემოსთვის**. საჯარო deployment-ისთვის საჭიროა იზოლირებული sandbox (მაგ. Docker worker / jail / ცალკე execution service).
