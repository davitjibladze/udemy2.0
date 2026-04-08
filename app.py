import json
import os
import re
import subprocess
import tempfile
import textwrap
from datetime import datetime
from functools import wraps
from slugify import slugify

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL not set")

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'გთხოვ, ჯერ შეხვიდე სისტემაში.'


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    courses = db.relationship('Course', backref='owner', lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False)
    short_description = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    chapters = db.relationship('Chapter', backref='course', lazy=True, cascade='all, delete-orphan', order_by='Chapter.position')
    reactions = db.relationship('CourseReaction', backref='course', lazy=True, cascade='all, delete-orphan')


class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    position = db.Column(db.Integer, default=1)

    lessons = db.relationship('Lesson', backref='chapter', lazy=True, cascade='all, delete-orphan', order_by='Lesson.position')


class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(240), unique=True, nullable=False)
    lesson_type = db.Column(db.String(20), nullable=False)  # text, quiz, code, match
    position = db.Column(db.Integer, default=1)
    intro = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    text_content = db.relationship('TextContent', backref='lesson', uselist=False, cascade='all, delete-orphan')
    video_content = db.relationship('VideoContent', backref='lesson', uselist=False, cascade='all, delete-orphan')
    quiz_questions = db.relationship('QuizQuestion', backref='lesson', lazy=True, cascade='all, delete-orphan')
    code_exercise = db.relationship('CodeExercise', backref='lesson', uselist=False, cascade='all, delete-orphan')
    matching_pairs = db.relationship('MatchingPair', backref='lesson', lazy=True, cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='lesson', lazy=True, cascade='all, delete-orphan')
    reactions = db.relationship('LessonReaction', backref='lesson', lazy=True, cascade='all, delete-orphan')
    completions = db.relationship('LessonCompletion', backref='lesson', lazy=True, cascade='all, delete-orphan')


class TextContent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)


class VideoContent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    embed_url = db.Column(db.String(500), nullable=False)


class QuizQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    explanation = db.Column(db.Text, default='')
    position = db.Column(db.Integer, default=1)

    options = db.relationship('QuizOption', backref='question', lazy=True, cascade='all, delete-orphan', order_by='QuizOption.position')


class QuizOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('quiz_question.id'), nullable=False)
    text = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)
    position = db.Column(db.Integer, default=1)


class CodeExercise(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    language = db.Column(db.String(30), default='python')
    prompt = db.Column(db.Text, nullable=False)
    starter_code = db.Column(db.Text, default='')
    solution_code = db.Column(db.Text, nullable=False)
    test_cases_json = db.Column(db.Text, nullable=False)

    def test_cases(self):
        return json.loads(self.test_cases_json or '[]')


class MatchingPair(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    left_text = db.Column(db.String(255), nullable=False)
    right_text = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, default=1)


class LessonCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    score = db.Column(db.Integer, default=0)
    max_score = db.Column(db.Integer, default=0)
    completed_at = db.Column(db.DateTime)

    __table_args__ = (UniqueConstraint('user_id', 'lesson_id', name='uq_user_lesson_completion'),)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User', backref='comments')
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy=True)
    reactions = db.relationship('CommentReaction', backref='comment', lazy=True, cascade='all, delete-orphan')


class CommentReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    value = db.Column(db.Integer, nullable=False)  # 1 or -1

    __table_args__ = (UniqueConstraint('comment_id', 'user_id', name='uq_comment_reaction'),)


class LessonReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    value = db.Column(db.Integer, nullable=False)

    __table_args__ = (UniqueConstraint('lesson_id', 'user_id', name='uq_lesson_reaction'),)


class CourseReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    value = db.Column(db.Integer, nullable=False)

    __table_args__ = (UniqueConstraint('course_id', 'user_id', name='uq_course_reaction'),)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('ადმინისტრატორის წვდომა საჭიროა.', 'error')
            return redirect(url_for('home'))
        return view_func(*args, **kwargs)
    return wrapper


def creator_required(course: Course):
    return current_user.is_authenticated and (current_user.is_admin or course.owner_id == current_user.id)


def upsert_completion(user_id: int, lesson_id: int, score: int, max_score: int, passed: bool):
    item = LessonCompletion.query.filter_by(user_id=user_id, lesson_id=lesson_id).first()
    if not item:
        item = LessonCompletion(user_id=user_id, lesson_id=lesson_id)
        db.session.add(item)
    item.score = score
    item.max_score = max_score
    item.status = 'passed' if passed else 'failed'
    item.completed_at = datetime.utcnow() if passed else None
    db.session.commit()


def get_course_progress(course: Course, user: User | None):
    progress = {'lessons': {}, 'chapters': {}, 'passed_lessons': 0, 'all_lessons': 0}
    if not user or not user.is_authenticated:
        return progress
    completions = {c.lesson_id: c for c in LessonCompletion.query.join(Lesson).join(Chapter).filter(
        LessonCompletion.user_id == user.id,
        Chapter.course_id == course.id
    ).all()}
    all_lessons = 0
    passed_lessons = 0
    for chapter in course.chapters:
        chapter_passed = True if chapter.lessons else False
        for lesson in chapter.lessons:
            all_lessons += 1
            comp = completions.get(lesson.id)
            passed = bool(comp and comp.status == 'passed')
            progress['lessons'][lesson.id] = passed
            if passed:
                passed_lessons += 1
            else:
                chapter_passed = False
        progress['chapters'][chapter.id] = chapter_passed
    progress['passed_lessons'] = passed_lessons
    progress['all_lessons'] = all_lessons
    return progress


def find_prev_next(lesson: Lesson):
    lessons = Lesson.query.join(Chapter).filter(Chapter.course_id == lesson.chapter.course_id).order_by(Chapter.position, Lesson.position).all()
    ids = [l.id for l in lessons]
    idx = ids.index(lesson.id)
    prev_lesson = lessons[idx - 1] if idx > 0 else None
    next_lesson = lessons[idx + 1] if idx < len(lessons) - 1 else None
    return prev_lesson, next_lesson


def lesson_score_counts(lesson: Lesson):
    likes = sum(1 for r in lesson.reactions if r.value == 1)
    dislikes = sum(1 for r in lesson.reactions if r.value == -1)
    return likes, dislikes


def course_score_counts(course: Course):
    likes = sum(1 for r in course.reactions if r.value == 1)
    dislikes = sum(1 for r in course.reactions if r.value == -1)
    return likes, dislikes


def comment_score(comment: Comment):
    likes = sum(1 for r in comment.reactions if r.value == 1)
    dislikes = sum(1 for r in comment.reactions if r.value == -1)
    return likes, dislikes


def save_reaction(model, field_name, entity_id, value):
    existing = model.query.filter_by(**{field_name: entity_id, 'user_id': current_user.id}).first()
    if not existing:
        existing = model(**{field_name: entity_id, 'user_id': current_user.id, 'value': value})
        db.session.add(existing)
    else:
        existing.value = value
    db.session.commit()


def evaluate_python_submission(code: str, exercise: CodeExercise):
    if not code.strip():
        return False, 'კოდი ცარიელია.', []

    if any(bad in code for bad in ['import os', 'import sys', 'subprocess', 'open(', '__import__', 'eval(', 'exec(', 'socket', 'pathlib']):
        return False, 'ამ MVP ვერსიაში სახიფათო იმპორტები გამორთულია.', []

    case_results = []
    for case in exercise.test_cases():
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, 'solution.py')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            try:
                result = subprocess.run(
                    ['python', file_path],
                    input=case.get('input', ''),
                    capture_output=True,
                    text=True,
                    timeout=2,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired:
                case_results.append({'input': case.get('input', ''), 'expected': case.get('output', ''), 'actual': 'Time limit exceeded', 'passed': False})
                continue
            actual = result.stdout.strip()
            expected = case.get('output', '').strip()
            passed = actual == expected and result.returncode == 0
            if result.stderr and result.returncode != 0:
                actual = result.stderr.strip()
                passed = False
            case_results.append({'input': case.get('input', ''), 'expected': expected, 'actual': actual, 'passed': passed})
    ok = all(item['passed'] for item in case_results)
    message = 'ყველა ტესტი წარმატებით გავიდა.' if ok else 'კოდი ყველა ტესტს ვერ გაივლის.'
    return ok, message, case_results


def seed_data():
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@ganatleba.ge')
    admin_password = os.getenv('ADMIN_PASSWORD', 'admin12345')
    admin = User.query.filter_by(email=admin_email).first()
    if not admin:
        admin = User(full_name='მთავარი ადმინისტრატორი', email=admin_email, is_admin=True)
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.flush()

    course = Course.query.filter_by(slug='python-start').first()
    if course:
        db.session.commit()
        return

    course = Course(
        owner_id=admin.id,
        title='Python-ის საფუძვლები დამწყებთათვის',
        slug='python-start',
        short_description='ქართული Stepik-ის სტილის დემო კურსი ვიდეოთი, ტესტებით, კოდით და კომენტარებით.',
        description='ამ დემო კურსში გაჩვენებულია ყველა ძირითადი ტიპის გაკვეთილი: ვიდეო, ტექსტი, ტესტი, კოდის ამოცანა და შესაბამისობის დავალება.',
        is_published=True,
    )
    db.session.add(course)
    db.session.flush()

    ch1 = Chapter(course_id=course.id, title='თავი 1 — დაწყება', position=1)
    ch2 = Chapter(course_id=course.id, title='თავი 2 — პრაქტიკა', position=2)
    db.session.add_all([ch1, ch2])
    db.session.flush()

    l1 = Lesson(chapter_id=ch1.id, title='ვიდეო გაკვეთილი', slug='python-start-video', lesson_type='text', position=1, intro='ჯერ უყურე ვიდეოს და გაეცანი ძირითად იდეებს.')
    db.session.add(l1); db.session.flush()
    db.session.add(TextContent(lesson_id=l1.id, body='## კურსის შესავალი\n\nეს კურსი აწყობილია თავებად და გაკვეთილებად. მარცხენა პანელში ხედავ პროგრესს — სწორი შესრულების შემდეგ თავი და გაკვეთილები გამწვანდება.'))
    db.session.add(VideoContent(lesson_id=l1.id, embed_url='https://www.youtube.com/embed/rfscVS0vtbw?si=2M0d3JQZQx7YlKQj'))

    l2 = Lesson(chapter_id=ch1.id, title='მოკლე დოკუმენტაცია', slug='python-start-docs', lesson_type='text', position=2, intro='ეს არის ტექსტური გაკვეთილის მაგალითი.')
    db.session.add(l2); db.session.flush()
    db.session.add(TextContent(lesson_id=l2.id, body='## ცვლადები და print()\n\nPython-ში მონაცემის შენახვა ხდება ცვლადში. მაგალითად:\n\n```python\nname = "Dato"\nprint(name)\n```\n\nგაკვეთილის ლაიქი/დისლაიქი და კომენტარები ქვემოთაა.'))

    l3 = Lesson(chapter_id=ch2.id, title='ტესტი checkbox-ებით', slug='python-start-quiz', lesson_type='quiz', position=1, intro='რამდენიმე კითხვას უპასუხე. სწორი ვარიანტი შეიძლება ერთზე მეტი იყოს.')
    db.session.add(l3); db.session.flush()
    q1 = QuizQuestion(lesson_id=l3.id, prompt='რომელი ვარიანტებია სწორი Python-ის შესახებ?', explanation='Python case-sensitive ენაა და print() ბეჭდავს ტექსტს.', position=1)
    db.session.add(q1); db.session.flush()
    db.session.add_all([
        QuizOption(question_id=q1.id, text='print() ტექსტს ეკრანზე გამოიტანს', is_correct=True, position=1),
        QuizOption(question_id=q1.id, text='Python-ში ცვლადის მინიჭება ხდება = ოპერატორით', is_correct=True, position=2),
        QuizOption(question_id=q1.id, text='ყველა if ბლოკი იწყება სიტყვით then', is_correct=False, position=3),
    ])
    q2 = QuizQuestion(lesson_id=l3.id, prompt='რომელი ვარიანტია სწორი?', explanation='if გამოიყენება პირობისთვის.', position=2)
    db.session.add(q2); db.session.flush()
    db.session.add_all([
        QuizOption(question_id=q2.id, text='if იწყებს პირობით ბლოკს', is_correct=True, position=1),
        QuizOption(question_id=q2.id, text='echo არის Python-ის სტანდარტული ფუნქცია', is_correct=False, position=2),
        QuizOption(question_id=q2.id, text='range() ხშირად გამოიყენება ციკლებში', is_correct=True, position=3),
    ])

    l4 = Lesson(chapter_id=ch2.id, title='კოდის ამოცანა', slug='python-start-code', lesson_type='code', position=2, intro='დაწერე პროგრამა, რომელიც კითხულობს ორ მთელ რიცხვს და ბეჭდავს მათ ჯამს.')
    db.session.add(l4); db.session.flush()
    db.session.add(CodeExercise(
        lesson_id=l4.id,
        language='python',
        prompt='შეიყვანე ორი მთელი რიცხვი ცალ-ცალკე ხაზზე და დაბეჭდე მათი ჯამი.',
        starter_code='a = int(input())\nb = int(input())\n# დაწერე პასუხი ქვემოთ\n',
        solution_code='a = int(input())\nb = int(input())\nprint(a + b)',
        test_cases_json=json.dumps([
            {'input': '2\n3\n', 'output': '5'},
            {'input': '10\n-4\n', 'output': '6'},
            {'input': '0\n0\n', 'output': '0'},
        ], ensure_ascii=False)
    ))

    l5 = Lesson(chapter_id=ch2.id, title='შესაბამისობის დავალება', slug='python-start-match', lesson_type='match', position=3, intro='მონიშნე რომელი განმარტება რომელ სიტყვას ეკუთვნის.')
    db.session.add(l5); db.session.flush()
    db.session.add_all([
        MatchingPair(lesson_id=l5.id, left_text='if', right_text='პირობითი ბლოკის დასაწყისი', position=1),
        MatchingPair(lesson_id=l5.id, left_text='for', right_text='ციკლის ოპერატორი', position=2),
        MatchingPair(lesson_id=l5.id, left_text='print', right_text='კონსოლში დაბეჭდვა', position=3),
    ])

    db.session.commit()


@app.context_processor
def inject_helpers():
    return {'lesson_score_counts': lesson_score_counts, 'course_score_counts': course_score_counts, 'comment_score': comment_score}


@app.route('/')
def home():
    courses = Course.query.filter_by(is_published=True).order_by(Course.created_at.desc()).all()
    course_count = len(courses)
    lesson_count = db.session.query(func.count(Lesson.id)).scalar() or 0
    user_count = db.session.query(func.count(User.id)).scalar() or 0
    return render_template('home.html', courses=courses[:6], course_count=course_count, lesson_count=lesson_count, user_count=user_count)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        if not full_name or not email or not password:
            flash('ყველა ველი სავალდებულოა.', 'error')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('ეს ელფოსტა უკვე გამოყენებულია.', 'error')
            return render_template('register.html')
        user = User(full_name=full_name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('რეგისტრაცია წარმატებულია.', 'success')
        return redirect(url_for('creator_dashboard'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash('ელფოსტა ან პაროლი არასწორია.', 'error')
            return render_template('login.html')
        login_user(user)
        flash('წარმატებით შეხვედი სისტემაში.', 'success')
        return redirect(url_for('creator_dashboard'))
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('ანგარიშიდან გამოხვედი.', 'success')
    return redirect(url_for('home'))


@app.route('/courses')
def course_list():
    courses = Course.query.filter_by(is_published=True).order_by(Course.created_at.desc()).all()
    return render_template('courses.html', courses=courses)


@app.route('/courses/<slug>')
def course_overview(slug):
    course = Course.query.filter_by(slug=slug).first_or_404()
    progress = get_course_progress(course, current_user)
    first_lesson = Lesson.query.join(Chapter).filter(Chapter.course_id == course.id).order_by(Chapter.position, Lesson.position).first()
    return render_template('course_overview.html', course=course, progress=progress, first_lesson=first_lesson)


@app.route('/courses/<slug>/react/<action>', methods=['POST'])
@login_required
def react_course(slug, action):
    course = Course.query.filter_by(slug=slug).first_or_404()
    save_reaction(CourseReaction, 'course_id', course.id, 1 if action == 'like' else -1)
    return redirect(url_for('course_overview', slug=slug))


@app.route('/courses/<slug>/lessons/<lesson_slug>', methods=['GET', 'POST'])
@login_required
def lesson_view(slug, lesson_slug):
    course = Course.query.filter_by(slug=slug).first_or_404()
    lesson = Lesson.query.join(Chapter).filter(Chapter.course_id == course.id, Lesson.slug == lesson_slug).first_or_404()
    progress = get_course_progress(course, current_user)
    prev_lesson, next_lesson = find_prev_next(lesson)
    submission_result = None

    if request.method == 'POST':
        if not current_user.is_authenticated:
            flash('გაკვეთილის შესასრულებლად საჭიროა ავტორიზაცია.', 'error')
            return redirect(url_for('login'))

        if lesson.lesson_type == 'text':
            upsert_completion(current_user.id, lesson.id, 1, 1, True)
            flash('გაკვეთილი მონიშნულია დასრულებულად.', 'success')
            return redirect(url_for('lesson_view', slug=slug, lesson_slug=lesson_slug))

        if lesson.lesson_type == 'quiz':
            total = len(lesson.quiz_questions)
            score = 0
            details = []
            for q in lesson.quiz_questions:
                selected_ids = sorted([int(v) for v in request.form.getlist(f'question_{q.id}')])
                correct_ids = sorted([opt.id for opt in q.options if opt.is_correct])
                ok = selected_ids == correct_ids
                if ok:
                    score += 1
                details.append({'question': q, 'selected_ids': selected_ids, 'correct_ids': correct_ids, 'passed': ok})
            passed = score == total
            upsert_completion(current_user.id, lesson.id, score, total, passed)
            submission_result = {'type': 'quiz', 'score': score, 'total': total, 'passed': passed, 'details': details}

        elif lesson.lesson_type == 'code':
            code = request.form.get('code', '')
            ok, message, case_results = evaluate_python_submission(code, lesson.code_exercise)
            upsert_completion(current_user.id, lesson.id, len([c for c in case_results if c['passed']]), len(case_results), ok)
            submission_result = {'type': 'code', 'passed': ok, 'message': message, 'cases': case_results, 'code': code}

        elif lesson.lesson_type == 'match':
            total = len(lesson.matching_pairs)
            score = 0
            pairs = lesson.matching_pairs
            details = []
            for pair in pairs:
                selected = request.form.get(f'pair_{pair.id}', '')
                ok = selected == pair.right_text
                if ok:
                    score += 1
                details.append({'pair': pair, 'selected': selected, 'passed': ok})
            passed = score == total
            upsert_completion(current_user.id, lesson.id, score, total, passed)
            submission_result = {'type': 'match', 'score': score, 'total': total, 'passed': passed, 'details': details}

    comments = Comment.query.filter_by(lesson_id=lesson.id, parent_id=None).order_by(Comment.created_at.desc()).all()
    return render_template('lesson_view.html', course=course, lesson=lesson, progress=progress, prev_lesson=prev_lesson, next_lesson=next_lesson, submission_result=submission_result, comments=comments)


@app.route('/lessons/<int:lesson_id>/react/<action>', methods=['POST'])
@login_required
def react_lesson(lesson_id, action):
    lesson = db.session.get(Lesson, lesson_id) or abort(404)
    save_reaction(LessonReaction, 'lesson_id', lesson.id, 1 if action == 'like' else -1)
    return redirect(url_for('lesson_view', slug=lesson.chapter.course.slug, lesson_slug=lesson.slug))


@app.route('/lessons/<int:lesson_id>/comments', methods=['POST'])
@login_required
def add_comment(lesson_id):
    lesson = db.session.get(Lesson, lesson_id) or abort(404)
    body = request.form.get('body', '').strip()
    parent_id = request.form.get('parent_id')
    if not body:
        flash('ცარიელი კომენტარი ვერ დაემატება.', 'error')
        return redirect(url_for('lesson_view', slug=lesson.chapter.course.slug, lesson_slug=lesson.slug))
    comment = Comment(lesson_id=lesson.id, user_id=current_user.id, body=body)
    if parent_id:
        comment.parent_id = int(parent_id)
    db.session.add(comment)
    db.session.commit()
    return redirect(url_for('lesson_view', slug=lesson.chapter.course.slug, lesson_slug=lesson.slug))


@app.route('/comments/<int:comment_id>/react/<action>', methods=['POST'])
@login_required
def react_comment(comment_id, action):
    comment = db.session.get(Comment, comment_id) or abort(404)
    save_reaction(CommentReaction, 'comment_id', comment.id, 1 if action == 'like' else -1)
    return redirect(url_for('lesson_view', slug=comment.lesson.chapter.course.slug, lesson_slug=comment.lesson.slug))


@app.route('/creator')
@login_required
def creator_dashboard():
    courses = Course.query.filter((Course.owner_id == current_user.id) | (current_user.is_admin == True)).order_by(Course.created_at.desc()).all()
    return render_template('creator_dashboard.html', courses=courses)


@app.route('/creator/courses/new', methods=['GET', 'POST'])
@login_required
def creator_new_course():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        short_description = request.form.get('short_description', '').strip()
        description = request.form.get('description', '').strip()
        if not title or not short_description or not description:
            flash('ყველა ველი სავალდებულოა.', 'error')
            return render_template('creator_new_course.html')
        base_slug = slugify(title) or f'course-{datetime.utcnow().timestamp()}'
        slug = base_slug
        counter = 2
        while Course.query.filter_by(slug=slug).first():
            slug = f'{base_slug}-{counter}'
            counter += 1
        course = Course(owner_id=current_user.id, title=title, slug=slug, short_description=short_description, description=description, is_published=True)
        db.session.add(course)
        db.session.commit()
        flash('კურსი შეიქმნა.', 'success')
        return redirect(url_for('creator_builder', course_id=course.id))
    return render_template('creator_new_course.html')


@app.route('/creator/courses/<int:course_id>/builder')
@login_required
def creator_builder(course_id):
    course = db.session.get(Course, course_id) or abort(404)
    if not creator_required(course):
        flash('წვდომა აკრძალულია.', 'error')
        return redirect(url_for('creator_dashboard'))
    return render_template('creator_builder.html', course=course)


@app.route('/creator/courses/<int:course_id>/chapters/new', methods=['POST'])
@login_required
def creator_add_chapter(course_id):
    course = db.session.get(Course, course_id) or abort(404)
    if not creator_required(course):
        abort(403)
    title = request.form.get('title', '').strip()
    if not title:
        flash('თავის დასახელება სავალდებულოა.', 'error')
        return redirect(url_for('creator_builder', course_id=course.id))
    pos = (db.session.query(func.max(Chapter.position)).filter_by(course_id=course.id).scalar() or 0) + 1
    db.session.add(Chapter(course_id=course.id, title=title, position=pos))
    db.session.commit()
    flash('თავი დაემატა.', 'success')
    return redirect(url_for('creator_builder', course_id=course.id))


@app.route('/creator/courses/<int:course_id>/lessons/new', methods=['GET', 'POST'])
@login_required
def creator_add_lesson(course_id):
    course = db.session.get(Course, course_id) or abort(404)
    if not creator_required(course):
        abort(403)
    chapters = course.chapters
    if not chapters:
        flash('ჯერ თავი შექმენი.', 'error')
        return redirect(url_for('creator_builder', course_id=course.id))

    if request.method == 'POST':
        chapter_id = int(request.form.get('chapter_id'))
        title = request.form.get('title', '').strip()
        lesson_type = request.form.get('lesson_type', '').strip()
        intro = request.form.get('intro', '').strip()
        if not title or lesson_type not in {'text', 'quiz', 'code', 'match'}:
            flash('სათაური და სწორი ტიპი აუცილებელია.', 'error')
            return render_template('creator_new_lesson.html', course=course, chapters=chapters)
        base_slug = slugify(f'{course.slug}-{title}') or f'lesson-{datetime.utcnow().timestamp()}'
        slug = base_slug
        counter = 2
        while Lesson.query.filter_by(slug=slug).first():
            slug = f'{base_slug}-{counter}'
            counter += 1
        pos = (db.session.query(func.max(Lesson.position)).filter_by(chapter_id=chapter_id).scalar() or 0) + 1
        lesson = Lesson(chapter_id=chapter_id, title=title, lesson_type=lesson_type, slug=slug, position=pos, intro=intro)
        db.session.add(lesson)
        db.session.flush()

        if lesson_type == 'text':
            body = request.form.get('body', '').strip()
            video_url = request.form.get('video_url', '').strip()
            db.session.add(TextContent(lesson_id=lesson.id, body=body or 'დოკუმენტაციის ტექსტი აქ ჩაწერე.'))
            if video_url:
                db.session.add(VideoContent(lesson_id=lesson.id, embed_url=video_url))

        elif lesson_type == 'quiz':
            prompt = request.form.get('question_prompt', '').strip()
            option_texts = [request.form.get(f'option_{i}', '').strip() for i in range(1, 5)]
            checked = set(request.form.getlist('correct_options'))
            question = QuizQuestion(lesson_id=lesson.id, prompt=prompt or 'კითხვა', explanation=request.form.get('explanation', '').strip(), position=1)
            db.session.add(question)
            db.session.flush()
            for idx, text in enumerate(option_texts, start=1):
                if text:
                    db.session.add(QuizOption(question_id=question.id, text=text, is_correct=(str(idx) in checked), position=idx))

        elif lesson_type == 'code':
            prompt = request.form.get('code_prompt', '').strip()
            starter_code = request.form.get('starter_code', '')
            solution_code = request.form.get('solution_code', '')
            tests_raw = request.form.get('tests_raw', '').strip()
            tests = []
            for block in tests_raw.split('\n\n'):
                if '=>' in block:
                    left, right = block.split('=>', 1)
                    tests.append({'input': left.strip() + ('\n' if not left.strip().endswith('\n') else ''), 'output': right.strip()})
            db.session.add(CodeExercise(lesson_id=lesson.id, language='python', prompt=prompt or 'კოდის ამოცანა', starter_code=starter_code, solution_code=solution_code or 'print(0)', test_cases_json=json.dumps(tests or [{'input': '1\n2\n', 'output': '3'}], ensure_ascii=False)))

        elif lesson_type == 'match':
            lefts = [request.form.get(f'left_{i}', '').strip() for i in range(1, 5)]
            rights = [request.form.get(f'right_{i}', '').strip() for i in range(1, 5)]
            for idx, (left, right) in enumerate(zip(lefts, rights), start=1):
                if left and right:
                    db.session.add(MatchingPair(lesson_id=lesson.id, left_text=left, right_text=right, position=idx))

        db.session.commit()
        flash('გაკვეთილი დაემატა.', 'success')
        return redirect(url_for('creator_builder', course_id=course.id))
    return render_template('creator_new_lesson.html', course=course, chapters=chapters)


@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    courses = Course.query.order_by(Course.created_at.desc()).all()
    return render_template('admin_dashboard.html', users=users, courses=courses)


@app.cli.command('init-db')
def init_db_command():
    db.drop_all()
    db.create_all()
    seed_data()
    print('Database initialized.')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()

    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
