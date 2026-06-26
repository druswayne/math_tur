from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import current_user
from sqlalchemy import text, inspect
import os
import secrets

db_admin_bp = Blueprint('db_admin', __name__, url_prefix='/admin/db')

db = None
DB_ADMIN_PASSWORD = None
DB_ADMIN_SESSION_KEY = 'db_admin_authenticated'


def init_db_admin(database):
    global db, DB_ADMIN_PASSWORD
    db = database
    DB_ADMIN_PASSWORD = os.environ.get('DB_ADMIN_PASSWORD')


def is_db_admin_authenticated():
    return session.get(DB_ADMIN_SESSION_KEY) is True


@db_admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))

    if not DB_ADMIN_PASSWORD:
        flash('Доступ к БД не настроен. Установите переменную DB_ADMIN_PASSWORD.', 'error')
        return redirect(url_for('admin_dashboard'))

    if is_db_admin_authenticated():
        return redirect(url_for('db_admin.index'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        if secrets.compare_digest(password, DB_ADMIN_PASSWORD):
            session[DB_ADMIN_SESSION_KEY] = True
            next_url = request.args.get('next') or url_for('db_admin.index')
            if not next_url.startswith('/admin/db'):
                next_url = url_for('db_admin.index')
            return redirect(next_url)
        flash('Неверный пароль', 'error')

    return render_template('db_admin/login.html')


@db_admin_bp.route('/logout', methods=['POST'])
def logout():
    session.pop(DB_ADMIN_SESSION_KEY, None)
    flash('Доступ к БД закрыт', 'success')
    return redirect(url_for('admin_dashboard'))


@db_admin_bp.before_request
def require_admin_access():
    if request.endpoint in ('db_admin.login', 'db_admin.logout'):
        return

    if not current_user.is_authenticated:
        return redirect(url_for('login', next=request.url))
    if not getattr(current_user, 'is_admin', False):
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))

    if not DB_ADMIN_PASSWORD:
        flash('Доступ к БД не настроен. Установите переменную DB_ADMIN_PASSWORD.', 'error')
        return redirect(url_for('admin_dashboard'))

    if not is_db_admin_authenticated():
        return redirect(url_for('db_admin.login', next=request.url))


def get_all_tables():
    inspector = inspect(db.engine)
    return inspector.get_table_names()


def get_table_structure(table_name):
    inspector = inspect(db.engine)
    columns = inspector.get_columns(table_name)
    pk_constraint = inspector.get_pk_constraint(table_name)
    pk_cols = set(pk_constraint.get('constrained_columns', []))

    for col in columns:
        col['primary_key'] = col['name'] in pk_cols

    return columns


def escape_table_name(table_name):
    reserved = {'user', 'order', 'group', 'select', 'table'}
    return f'"{table_name}"' if table_name.lower() in reserved else table_name


def get_primary_key(table_name):
    inspector = inspect(db.engine)
    pk_constraint = inspector.get_pk_constraint(table_name)
    pk_cols = pk_constraint.get('constrained_columns', [])

    if pk_cols:
        return pk_cols[0]

    columns = inspector.get_columns(table_name)
    for col in columns:
        if col['name'].lower() == 'id':
            return col['name']

    if columns:
        return columns[0]['name']

    return 'id'


def get_table_data(table_name, page=1, per_page=50, search=None, search_field=None):
    offset = (page - 1) * per_page

    safe_table_name = escape_table_name(table_name)

    query = f"SELECT * FROM {safe_table_name}"
    count_query = f"SELECT COUNT(*) as count FROM {safe_table_name}"

    params = {}

    if search:
        columns = get_table_structure(table_name)

        if search_field:
            column_names = [col['name'] for col in columns]
            if search_field in column_names:
                search_column = next((col for col in columns if col['name'] == search_field), None)
                if search_column:
                    column_name = search_column['name']
                    column_type = str(search_column.get('type', '')).lower()

                    if any(t in column_type for t in ['integer', 'bigint', 'smallint', 'numeric', 'decimal', 'real', 'double', 'boolean', 'timestamp', 'date', 'time']):
                        query += f" WHERE CAST({column_name} AS TEXT) LIKE :search_value"
                        count_query += f" WHERE CAST({column_name} AS TEXT) LIKE :search_value"
                    else:
                        query += f" WHERE {column_name} LIKE :search_value"
                        count_query += f" WHERE {column_name} LIKE :search_value"

                    params['search_value'] = f"%{search}%"
            else:
                search_field = None

        if not search_field:
            search_conditions = []
            for i, column in enumerate(columns):
                param_name = f"search_{i}"
                column_name = column['name']
                column_type = str(column.get('type', '')).lower()

                if any(t in column_type for t in ['integer', 'bigint', 'smallint', 'numeric', 'decimal', 'real', 'double', 'boolean', 'timestamp', 'date', 'time']):
                    search_conditions.append(f"CAST({column_name} AS TEXT) LIKE :{param_name}")
                else:
                    search_conditions.append(f"{column_name} LIKE :{param_name}")

                params[param_name] = f"%{search}%"
            search_where = " OR ".join(search_conditions)
            query += f" WHERE {search_where}"
            count_query += f" WHERE {search_where}"

    query += f" LIMIT {per_page} OFFSET {offset}"

    with db.engine.connect() as conn:
        result = conn.execute(text(query), params)
        data = [dict(row._mapping) for row in result]

        count_result = conn.execute(text(count_query), params)
        total_count = count_result.fetchone()[0]

    return data, total_count


@db_admin_bp.route('/')
def index():
    tables = get_all_tables()
    return render_template('db_admin/index.html', tables=tables)


@db_admin_bp.route('/table/<table_name>')
def view_table(table_name):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '')
    search_field = request.args.get('search_field', '')

    try:
        data, total_count = get_table_data(table_name, page, per_page, search, search_field if search_field else None)
        structure = get_table_structure(table_name)

        total_pages = (total_count + per_page - 1) // per_page

        return render_template('db_admin/table.html',
                             table_name=table_name,
                             data=data,
                             structure=structure,
                             page=page,
                             per_page=per_page,
                             total_pages=total_pages,
                             total_count=total_count,
                             search=search,
                             search_field=search_field)
    except Exception as e:
        flash(f'Ошибка при загрузке таблицы: {str(e)}', 'error')
        return redirect(url_for('db_admin.index'))


@db_admin_bp.route('/table/<table_name>/edit/<int:row_id>', methods=['GET', 'POST'])
def edit_row(table_name, row_id):
    if request.method == 'GET':
        try:
            structure = get_table_structure(table_name)
            primary_key = get_primary_key(table_name)

            safe_table_name = escape_table_name(table_name)

            with db.engine.connect() as conn:
                result = conn.execute(text(f"SELECT * FROM {safe_table_name} WHERE {primary_key} = :pk"), {"pk": row_id})
                row = result.fetchone()
                if row:
                    return render_template('db_admin/edit_row.html',
                                         table_name=table_name,
                                         row=dict(row._mapping),
                                         structure=structure,
                                         primary_key=primary_key)
                else:
                    flash('Запись не найдена', 'error')
                    return redirect(url_for('db_admin.view_table', table_name=table_name))
        except Exception as e:
            flash(f'Ошибка при загрузке записи: {str(e)}', 'error')
            return redirect(url_for('db_admin.view_table', table_name=table_name))

    elif request.method == 'POST':
        try:
            structure = get_table_structure(table_name)
            primary_key = get_primary_key(table_name)

            update_data = {}

            for column in structure:
                column_name = column['name']
                if column_name in request.form:
                    value = request.form[column_name]
                    if value == '' and column.get('nullable', True):
                        update_data[column_name] = None
                    else:
                        update_data[column_name] = value

            safe_table_name = escape_table_name(table_name)

            set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
            query = f"UPDATE {safe_table_name} SET {set_clause} WHERE {primary_key} = :pk"
            update_data['pk'] = row_id

            with db.engine.begin() as conn:
                conn.execute(text(query), update_data)

            flash('Запись успешно обновлена', 'success')
            return redirect(url_for('db_admin.view_table', table_name=table_name))

        except Exception as e:
            flash(f'Ошибка при обновлении записи: {str(e)}', 'error')
            return redirect(url_for('db_admin.edit_row', table_name=table_name, row_id=row_id))


@db_admin_bp.route('/table/<table_name>/delete/<int:row_id>', methods=['POST'])
def delete_row(table_name, row_id):
    try:
        primary_key = get_primary_key(table_name)

        safe_table_name = escape_table_name(table_name)

        with db.engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {safe_table_name} WHERE {primary_key} = :pk"), {"pk": row_id})

        flash('Запись успешно удалена', 'success')
        return redirect(url_for('db_admin.view_table', table_name=table_name))

    except Exception as e:
        error_message = str(e)

        if 'ForeignKeyViolation' in error_message:
            if 'teacher_cart_item' in error_message or 'user_cart_item' in error_message:
                flash('Нельзя удалить запись: данный приз используется в корзинах. Используйте кнопку "Удалить с очисткой" для автоматического удаления связанных записей.', 'error')
            elif 'order_item' in error_message:
                flash('Нельзя удалить запись: данный приз используется в заказах. Сначала удалите связанные записи из заказов.', 'error')
            else:
                flash('Нельзя удалить запись: она используется в других таблицах. Сначала удалите связанные записи.', 'error')
        else:
            flash(f'Ошибка при удалении записи: {error_message}', 'error')

        return redirect(url_for('db_admin.view_table', table_name=table_name))


@db_admin_bp.route('/table/<table_name>/add', methods=['GET', 'POST'])
def add_row(table_name):
    if request.method == 'GET':
        structure = get_table_structure(table_name)
        return render_template('db_admin/add_row.html',
                             table_name=table_name,
                             structure=structure)

    elif request.method == 'POST':
        try:
            structure = get_table_structure(table_name)
            insert_data = {}

            for column in structure:
                column_name = column['name']
                if column_name != 'id' and column_name in request.form:
                    value = request.form[column_name]
                    if value == '' and column.get('nullable', True):
                        insert_data[column_name] = None
                    else:
                        insert_data[column_name] = value

            columns = ", ".join(insert_data.keys())
            values = ", ".join([f":{k}" for k in insert_data.keys()])
            query = f"INSERT INTO {table_name} ({columns}) VALUES ({values})"

            with db.engine.begin() as conn:
                conn.execute(text(query), insert_data)

            flash('Запись успешно добавлена', 'success')
            return redirect(url_for('db_admin.view_table', table_name=table_name))

        except Exception as e:
            flash(f'Ошибка при добавлении записи: {str(e)}', 'error')
            return redirect(url_for('db_admin.add_row', table_name=table_name))


@db_admin_bp.route('/table/<table_name>/cleanup/<int:row_id>', methods=['POST'])
def cleanup_related_records(table_name, row_id):
    try:
        primary_key = get_primary_key(table_name)

        deleted_count = 0

        with db.engine.begin() as conn:
            result = conn.execute(text("DELETE FROM teacher_cart_item WHERE prize_id = :pk"), {"pk": row_id})
            deleted_count += result.rowcount

            result = conn.execute(text("DELETE FROM user_cart_item WHERE prize_id = :pk"), {"pk": row_id})
            deleted_count += result.rowcount

            safe_table_name = escape_table_name(table_name)

            conn.execute(text(f"DELETE FROM {safe_table_name} WHERE {primary_key} = :pk"), {"pk": row_id})

        flash(f'Запись и связанные записи успешно удалены. Удалено {deleted_count} связанных записей.', 'success')
        return redirect(url_for('db_admin.view_table', table_name=table_name))

    except Exception as e:
        flash(f'Ошибка при очистке связанных записей: {str(e)}', 'error')
        return redirect(url_for('db_admin.view_table', table_name=table_name))


@db_admin_bp.route('/api/table/<table_name>/data')
def api_table_data(table_name):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '')
    search_field = request.args.get('search_field', '')

    try:
        data, total_count = get_table_data(table_name, page, per_page, search, search_field if search_field else None)
        return jsonify({
            'data': data,
            'total_count': total_count,
            'page': page,
            'per_page': per_page
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@db_admin_bp.context_processor
def inject_template_functions():
    return {
        'min': min,
        'max': max,
        'len': len,
        'str': str,
        'int': int,
        'float': float,
        'bool': bool,
        'list': list,
        'dict': dict,
        'range': range
    }
