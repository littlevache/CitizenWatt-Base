#!/usr/bin/env python3

import datetime
import requests
import time

from math import sin
from random import random
from json import load, dumps

from bottle import abort, Bottle, SimpleTemplate, static_file, redirect, request, run
from bottle.ext import sqlalchemy
from bottlesession import PickleSession, authenticator
from sqlalchemy import create_engine, Column, DateTime, asc, event, Float, ForeignKey, Integer, Text, VARCHAR
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func

MAX_VALUES = 500

def to_dict(model):
    """ Returns a JSON representation of an SQLAlchemy-backed object.
    TODO : Use runtime inspection API
    From https://zato.io/blog/posts/converting-sqlalchemy-objects-to-json.html
    """
    dict = {}
    dict['id'] = getattr(model, 'id')

    for col in model._sa_class_manager.mapper.mapped_table.columns:
        dict[col.name] = getattr(model, col.name)

    return dict

n_values = 0
def generate_value():
    """Generate values for debug purpose"""
    global n_values
    MAX_POWER = 3500
    n_values += 1
    return sin(n_values / 10.0) ** 2 * MAX_POWER
    return random() * MAX_POWER

def get_rate_type(db):
    """Returns "day" or "night"
    """
    session = session_manager.get_session()
    user = db.query(User).filter_by(login=session["login"]).first()
    now = datetime.datetime.now()
    now = 3600 * now.hour + 60 * now.minute
    if user is None:
        return -1
    elif user.end_night_rate > user.start_night_rate:
        if now > user.start_night_rate and now < user.end_night_rate:
            return "night"
        else:
            return "day"
    else:
        if now > user.start_night_rate or now < user.end_night_rate:
            return "night"
        else:
            return "day"

#@event.listens_for(Engine, "connect")
#def set_sqlite_pragma(dbapi_connection, connection_record):
#    """Enables foreign keys in SQLite"""
#    cursor = dbapi_connection.cursor()
#    cursor.execute("PRAGMA foreign_keys=ON")
#    cursor.close()

Base = declarative_base()
username = "citizenwatt"
password = "citizenwatt"
database = "citizenwatt"
host = "localhost"
engine = create_engine("mysql+pymysql://"+username+":"+password+"@"+host+"/"+database, echo=True)

app = Bottle()
plugin = sqlalchemy.Plugin(
    engine,
    Base.metadata,
    keyword='db',
    create=True,
    commit=True,
    use_kwargs=False
)
app.install(plugin)

session_manager = PickleSession()
valid_user = authenticator(session_manager, login_url='/login')

# DB Structure

class Sensor(Base):
    __tablename__ = "sensors"
    id = Column(Integer, primary_key=True)
    name = Column(VARCHAR(255), unique=True)
    type_id = Column(Integer,
                     ForeignKey("measures_types.id", ondelete="CASCADE"),
                     nullable=False)
    measures = relationship("Measures", passive_deletes=True)
    type = relationship("MeasureType", lazy="joined")


class Measures(Base):
    __tablename__ = "measures"
    id = Column(Integer, primary_key=True)
    sensor_id = Column(Integer,
                       ForeignKey("sensors.id", ondelete="CASCADE"),
                       nullable=False)
    value = Column(Float)
    timestamp = Column(DateTime)
    night_rate = Column(Integer)  # Boolean, 1 if night_rate


class Provider(Base):
    __tablename__ = "providers"
    id = Column(Integer, primary_key=True)
    name = Column(VARCHAR(length=255), unique=True)
    type_id = Column(Integer,
                     ForeignKey("measures_types.id", ondelete="CASCADE"),
                     nullable=False)
    slope_watt_euros = Column(Float)
    constant_watt_euros = Column(Float)
    current = Column(Integer)


class MeasureType(Base):
    __tablename__ = "measures_types"
    id = Column(Integer, primary_key=True)
    name = Column(VARCHAR(255), unique=True)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    login = Column(VARCHAR(length=255), unique=True)
    password = Column(Text)
    is_admin = Column(Integer)
    start_night_rate = Column(Integer)  # Stored as seconds since beginning of day
    end_night_rate = Column(Integer)  # Stored as seconds since beginning of day


# Useful functions
def update_providers(db):
    # json = requests.get("http://pub.phyks.me/tmp/electricity_providers.json")
    with open("electricity_providers.json", "r") as fh:
        providers = load(fh)
    old_current = db.query(Provider).filter_by(current=1).first()
    db.query(Provider).delete()
    #providers = json.json()
    for provider in providers:
        provider_db = Provider(name=provider["name"],
                               constant_watt_euros=provider["constant_watt_euros"],
                               slope_watt_euros=provider["slope_watt_euros"],
                               type_id=provider["type_id"],
                               current=(1 if old_current and old_current.name == provider["name"] else 0))
        db.add(provider_db)
    return providers

def last_day(month, year):
    if month in [1, 3, 5, 7, 8, 10, 12]:
        return 31
    elif month == 2:
        if year % 4 == 0 and (not year % 100 or year % 400):
            return 29
        else:
            return 28
    else:
        return 30


# API
@app.route("/api/sensors", apply=valid_user())
def api_sensors(db):
    sensors = db.query(Sensor).all()
    if sensors:
        sensors = [{"id": sensor.id,
                    "name": sensor.name,
                    "type": sensor.type.name,
                    "type_id": sensor.type_id
                } for sensor in sensors]
        return {"data": sensors}
    else:
        abort(404, "No sensors found.")

@app.route("/api/<sensor:int>/get/watts/by_id/<id1:int>", apply=valid_user())
def api_get_id(sensor, watt_euros, id1, db):
    # DEBUG
    #data = [{"power": generate_value()} for i in range(id1)]
    #if watt_euros == "euros":
    #    data = [{"power": api_watt_euros(0, i["power"], db)["data"]} for i in data]
    #return {"data": data, "rate": get_rate_type(db)}
    # /DEBUG

    if id1 >= 0:
        data = db.query(Measures).filter_by(sensor_id=sensor,
                                            id=id1).first()
    else:
        data = db.query(Measures).filter_by(sensor_id=sensor).order_by(asc(Measures.id)).slice(id1, id1)

    if data:
        data = to_dict(data)
        return {"data": data, "rate": get_rate_type(db)}
    else:
        abort(404,
              "No measures with id " + str(id1)  +
              " found for sensor " + str(sensor) + ".")

@app.route("/api/<sensor:int>/get/<watt_euros:re:watts|euros>/by_id/<id1:int>/<id2:int>", apply=valid_user())
def api_get_ids(sensor, watt_euros, id1, id2, db):
    # DEBUG
    #data = [{"power": generate_value()} for i in range(id1, id2)]
    #if watt_euros == "euros":
    #    data = [{"power": api_watt_euros(0, i["power"], db)["data"]} for i in data]
    #return {"data": data, "rate": get_rate_type(db)}
    # /DEBUG

    if id1 >= 0 and id2 >= 0 and id2 >= id1:
        data = db.query(Measures).filter(sensor_id == sensor,
                                         id >= id1,
                                         id <= id2).all()
    elif id1 <= 0 and id2 <= 0 and id2 >= id1:
        data = db.query(Measures).filter_by(sensor_id=sensor).order_by(asc(Measures.id)).slice(-id2,-id1).all()
    else:
        abort(404, "Wrong parameters id1 and id2.")

    if (id2 - id1) > MAX_VALUES:
        abort(403, "Too many values to return. (Maximum is set to %d)" % (MAX_VALUES,))

    if data:
        data = to_dict(data)
        if watt_euros == 'euros':
            energy = 0
            old_timestamp = 0
            for i in data:
                energy += i["power"] / 1000 * (i["timestamp"] - old_timestamp) / 3600
                old_timestamp = i["timestamp"]
            data = [{"power": api_watt_euros(0, energy, db)["data"]} for i in data]
        return {"data": data, "rate": get_rate_type(db)}
    else:
        abort(404,
              "No relevant measures found.")

@app.route("/api/<sensor:int>/get/watts/by_time/<time1:float>", apply=valid_user())
def api_get_time(sensor, watt_euros, time1, db):
    if time1 < 0:
        abort(404, "Invalid timestamp.")

    # DEBUG
    #data = [{"power": generate_value()} for i in range(int(time1))]
    #if watt_euros == "euros":
    #    data = [{"power": api_watt_euros(0, i["power"], db)["data"]} for i in data]
    #return {"data": data, "rate": get_rate_type(db)}
    # /DEBUG

    data = db.query(Measures).filter_by(sensor_id=sensor,
                                        timestamp=time1).first()
    if data:
        data = to_dict(data)
        return {"data": data, "rate": get_rate_type(db)}
    else:
        abort(404,
              "No measures at timestamp " + str(time1) +
              " found for sensor " + str(sensor) + ".")

@app.route("/api/<sensor:int>/get/<watt_euros:re:watts|euros>/by_time/<time1:float>/<time2:float>",
           apply=valid_user())
def api_get_times(sensor, watt_euros, time1, time2, db):
    if time1 < 0 or time2 < time1:
        abort(404, "Invalid timestamps.")

    if (time2 - time1) > MAX_VALUES:
        abort(403, "Too many values to return. (Maximum is set to %d)" % (MAX_VALUES,))

    # DEBUG
    #data = [{"power": generate_value()} for i in range(int(time1), int(time2))]
    #if watt_euros == "euros":
    #    data = [{"power": api_watt_euros(0, i["power"], db)["data"]} for i in data]
    #return {"data": data, "rate": get_rate_type(db)}
    # /DEBUG

    data = db.query(Measures).filter(sensor_id == sensor,
                                     timestamp >= time1,
                                     timestamp <= time2).all()
    if data:
        data = to_dict(data)
        if watt_euros == 'euros':
            energy = 0
            old_timestamp = 0
            for i in data:
                energy += i["power"] / 1000 * (i["timestamp"] - old_timestamp) / 3600
                old_timestamp = i["timestamp"]
            data = [{"power": api_watt_euros(0, energy, db)["data"]} for i in data]
        return {"data": data, "rate": get_rate_type(db)}
    else:
        abort(404,
              "No measures between timestamp " + str(time1) +
              " and timestamp " + str(time2) +
              " found for sensor " + str(sensor) + ".")

@app.route("/api/energy_providers", apply=valid_user())
def api_energy_providers(db):
    providers = db.query(Provider).all()
    if providers:
        return {"data": [to_dict(provider) for provider in providers]}
    else:
        abort(404, 'No providers found.')

@app.route("/api/energy_providers/<id:re:current|\d*>", apply=valid_user())
def api_specific_energy_providers(id, db):
    if id == "current":
        provider = db.query(Provider).filter_by(current=1).first()
    else:
        try:
            id = int(id)
        except ValueError:
            abort(404, "Invalid parameter.")

        provider = db.query(Provider).filter_by(id=id).first()
    if provider:
        return {"data": to_dict(provider)}
    else:
        abort(404, 'No providers found.')

@app.route("/api/<energy_provider:int>/watt_euros/<consumption:float>",
           apply=valid_user())
def api_watt_euros(energy_provider, consumption, db):
    # Consumption should be in kWh !!!
    if energy_provider != 0:
        provider = db.query(Provider).filter_by(id=energy_provider).first()
    else:
        provider = db.query(Provider).filter_by(current=1).first()
    if provider:
        return {"data": provider.slope_watt_euros * consumption + provider.constant_watt_euros}
    else:
        abort(404, 'No matching provider found.')

@app.route("/api/<sensor_id:int>/mean/<watt_euros:re:watts|kwatthours|euros>/<day_month:re:daily|weekly|monthly>",
           apply=valid_user())
def api_mean(sensor_id, watt_euros, day_month, db):
    now = datetime.datetime.now()
    if day_month == "daily":
        # DEBUG
        #return {"data": {"global": 354, "hourly": [150, 100, 200, 400,
        #                                                2000, 4000, 234, 567,
        #                                                6413, 131, 364, 897,
        #                                                764, 264, 479, 20,
        #                                                274, 2644, 679, 69,
        #                                                264, 724, 274, 987]}, "rate": get_rate_type(db)}
        # /DEBUG
        length_step = 3600
        day_start = datetime.datetime(now.year, now.month, now.day, 0, 0, 0, 0)
        day_end = datetime.datetime(now.year, now.month, now.day, 23, 59, 59, 999)
        time_start = int(time.mktime(day_start.timetuple()))
        time_end = int(time.mktime(day_end.timetuple()))
        times = []
        for time_i in range(time_start, time_end, length_step):
            times.append(time_i)
        times.append(time_end)
        hour_day = "hourly"
    elif day_month == "weekly":
        # DEBUG
        #return {"data": {"global": 354, "daily": [150, 100, 200, 400,
        #                                                2000, 4000, 234]}, "rate": get_rate_type(db)}
        # /DEBUG
        length_step = 86400
        day_start = datetime.datetime(now.year, now.month, now.day - now.weekday(), 0, 0, 0, 0)
        day_end = datetime.datetime(now.year, now.month, now.day + 6 - now.weekday(), 23, 59, 59, 999)
        time_start = int(time.mktime(day_start.timetuple()))
        time_end = int(time.mktime(day_end.timetuple()))
        times = []
        for time_i in range(time_start, time_end, length_step):
            times.append(time_i)
        times.append(time_end)
        hour_day = "daily"
    elif day_month == "monthly":
        # DEBUG
        #return {"data": {"global": 354, "daily": [150, 100, 200, 400,
        #                                               2000, 4000, 234, 567,
        #                                               6413, 131, 364, 897,
        #                                               764, 264, 479, 20,
        #                                               274, 2644, 679, 69,
        #                                               264, 724, 274, 987,
        #                                               753, 746, 2752, 175,
        #                                               276, 486, 243]}, "rate": get_rate_type(db)}
        # /DEBUG
        length_step = 86400
        month_start = datetime.datetime(now.year, now.month, 1, 0, 0, 0, 0)
        month_end = datetime.datetime(now.year, now.month, last_day(now.month, now.year), 23, 59, 59, 999)
        time_start = int(time.mktime(month_start.timetuple()))
        time_end = int(time.mktime(month_end.timetuple()))
        times = []
        for time_i in range(time_start, time_end, length_step):
            times.append(time_i)
        times.append(time_end)
        hour_day = "daily"

    means = []
    for i in range(len(times) - 1):
        means.append(db.query((func.avg(Measures.value)).label('average')).filter(Measures.timestamp >= times[i],
                                                                                  Measures.timestamp <= times[i+1]).first())
        if not means or means[-1] == (None,):
            means[-1] = [-1]

    # TODO : global_mean is mean of mean
    global_mean = db.query((func.avg(Measures.value)).label('average')).filter(Measures.timestamp >= times[0],
                                                                               Measures.timestamp <= times[-1]).first()
    if global_mean == (None,):
        global_mean = [-1]

    if global_mean:
        if watt_euros == "euros" or watt_euros == "kwatthours":
            global_mean = global_mean[0] * (times[-1] - times[0])
            means = [mean[0] * length_step / 1000 / 3600 for mean in means]
            if watt_euros == "euros":
                global_mean = api_watt_euros(0, global_mean, db)
                means = [api_watt_euros(0, mean, db)["data"] if mean[0] != -1 else -1 for mean in mean]
        else:
            global_mean = global_mean[0]
            means = [mean[0] for mean in means]
        return {"data": {"global": global_mean, hour_day: means }, "rate": get_rate_type(db)}
    else:
        abort(404,
              "No measures available for sensor " + str(sensor_id) + " to " +
              "compute the "+day_month+" mean.")

# Routes
@app.route("/static/<filename:path>", name="static")
def static(filename):
    return static_file(filename, root="static")


@app.route('/', name="index", template="index", apply=valid_user())
def index():
    return {}


@app.route("/conso", name="conso", template="conso", apply=valid_user())
def conso(db):
    provider = db.query(Provider).filter_by(current=1).first()
    return {"provider": provider.name}

@app.route("/settings", name="settings", template="settings")
def settings(db):
    sensors = db.query(Sensor).all()
    if sensors:
        sensors = [{"id": sensor.id,
                    "name": sensor.name,
                    "type": sensor.type.name,
                    "type_id": sensor.type_id
                } for sensor in sensors]
    else:
        sensors = []

    providers = update_providers(db)

    session = session_manager.get_session()
    user = db.query(User).filter_by(login=session["login"]).first()
    start_night_rate = ("%02d" % (user.start_night_rate // 3600) + ":" +
                        "%02d" % (user.start_night_rate % 3600))
    end_night_rate = ("%02d" % (user.end_night_rate // 3600) + ":" +
                      "%02d" % (user.end_night_rate % 3600))

    return {"sensors": sensors,
            "providers": providers,
            "start_night_rate": start_night_rate,
            "end_night_rate": end_night_rate}

@app.route("/settings",
           name="settings",
           apply=valid_user(),
           method="post")
def settings_post(db):
    password = request.forms.get("password").strip()
    password_confirm = request.forms.get("password_confirm")

    if password:
        if password == password_confirm:
            session = session_manager.get_session()
            user = (db.query(User).filter_by(login=session["login"]).
                    update({"password": password},  synchronize_session=False))
        else:
            abort(400, "Les mots de passe ne sont pas identiques.")

    provider = request.forms.get("provider")
    provider = (db.query(Provider).filter_by(name=provider).\
                update({"current":1}))

    raw_start_night_rate = request.forms.get("start_night_rate")
    raw_end_night_rate = request.forms.get("end_night_rate")

    error = None

    try:
        start_night_rate = raw_start_night_rate.split(":")
        assert(len(start_night_rate) == 2)
        start_night_rate = [int(i) for i in start_night_rate]
        assert(start_night_rate[0] >= 0 and start_night_rate[0] <= 23)
        assert(start_night_rate[1] >= 0 and start_night_rate[1] <= 59)
        start_night_rate = 3600 * start_night_rate[0] + 60*start_night_rate[1]
    except (AssertionError,ValueError):
        error = {"title":"Format invalide",
                 "content": "La date de début d'heures creuses doit être au format hh:mm."}
    try:
        end_night_rate = raw_end_night_rate.split(":")
        assert(len(end_night_rate) == 2)
        end_night_rate = [int(i) for i in end_night_rate]
        assert(end_night_rate[0] >= 0 and end_night_rate[0] <= 23)
        assert(end_night_rate[1] >= 0 and end_night_rate[1] <= 59)
        end_night_rate = 3600 * end_night_rate[0] + 60*end_night_rate[1]
    except (AssertionError, ValueError):
        error = {"title":"Format invalide",
                 "content": "La date de fin d'heures creuses doit être au format hh:mm."}

    session = session_manager.get_session()
    user = db.query(User).filter_by(login=session["login"]).update({"start_night_rate": start_night_rate,
                                                                    "end_night_rate": end_night_rate})

    redirect("/settings")

@app.route("/store", name="store", template="store")
def store():
    return {}

@app.route("/help", name="help", template="help")
def help():
    return {}


@app.route("/login", name="login", template="login")
def login(db):
    if not db.query(User).all():
        redirect("/install")
    session = session_manager.get_session()
    if session['valid'] is True:
        redirect('/')
    else:
        return {"login": ''}


@app.route("/login", name="login", template="login", method="post")
def login(db):
    login = request.forms.get("login")
    user = db.query(User).filter_by(login=login).first()
    session = session_manager.get_session()
    session['valid'] = False
    session_manager.save(session)
    if user and user.password == request.forms.get("password"):
        session['valid'] = True
        session['login'] = login
        session['is_admin'] = user.is_admin
        session_manager.save(session)
        redirect('/')
    else:
        return {
            "login": login,
            "err": {
                "title": "Identifiants incorrects.",
                "content": "Aucun utilisateur n'est enregistré à ce nom." if user else "Mot de passe erroné."
            }
        }


@app.route("/logout", name="logout")
def logout():
    session = session_manager.get_session()
    session['valid'] = False
    del(session['login'])
    del(session['is_admin'])
    session_manager.save(session)
    redirect('/')


@app.route("/install", name="install", template="install")
def install(db):
    if db.query(User).all():
        redirect('/')

    db.query(MeasureType).delete()
    db.query(Provider).delete()
    db.query(Sensor).delete()

    electricity_type = MeasureType(name="Électricité")
    db.add(electricity_type)
    db.flush()

    providers = update_providers(db)

    sensor = Sensor(name="CitizenWatt",
                    type_id=electricity_type.id)
    db.add(sensor)

    return {"login": '', "providers": providers,
            "start_night_rate": '', "end_night_rate": ''}

@app.route("/install", name="install", template="install", method="post")
def install_post(db):
    try:
        if db.query(User).all():
            redirect('/')
    except OperationalError:
        redirect('/')

    login = request.forms.get("login").strip()
    password = request.forms.get("password").strip()
    password_confirm = request.forms.get("password_confirm")
    provider = request.forms.get("provider")
    raw_start_night_rate = request.forms.get("start_night_rate")
    raw_end_night_rate = request.forms.get("end_night_rate")

    error = None

    try:
        start_night_rate = raw_start_night_rate.split(":")
        assert(len(start_night_rate) == 2)
        start_night_rate = [int(i) for i in start_night_rate]
        assert(start_night_rate[0] >= 0 and start_night_rate[0] <= 23)
        assert(start_night_rate[1] >= 0 and start_night_rate[1] <= 59)
        start_night_rate = 3600 * start_night_rate[0] + 60*start_night_rate[1]
    except (AssertionError,ValueError):
        error = {"title":"Format invalide",
                 "content": "La date de début d'heures creuses doit être au format hh:mm."}
    try:
        end_night_rate = raw_end_night_rate.split(":")
        assert(len(end_night_rate) == 2)
        end_night_rate = [int(i) for i in end_night_rate]
        assert(end_night_rate[0] >= 0 and end_night_rate[0] <= 23)
        assert(end_night_rate[1] >= 0 and end_night_rate[1] <= 59)
        end_night_rate = 3600 * end_night_rate[0] + 60*end_night_rate[1]
    except (AssertionError, ValueError):
        error = {"title":"Format invalide",
                 "content": "La date de fin d'heures creuses doit être au format hh:mm."}


    if login and password and password == password_confirm and not error:

        admin = User(login=login, password=password, is_admin=1,
                     start_night_rate=start_night_rate,
                     end_night_rate=end_night_rate)
        db.add(admin)

        provider = (db.query(Provider).filter_by(name=provider).\
                    update({"current":1}))

        session = session_manager.get_session()
        session['valid'] = True
        session['login'] = login
        session['is_admin'] = 1
        session_manager.save(session)

        redirect('/')
    else:
        providers = update_providers(db)
        ret = {"login": login, "providers": providers, "start_night_rate": raw_start_night_rate,
                "end_night_rate": raw_end_night_rate}
        if error:
            ret['err'] = error
        return ret

SimpleTemplate.defaults["get_url"] = app.get_url
SimpleTemplate.defaults["API_URL"] = app.get_url("index")
SimpleTemplate.defaults["valid_session"] = lambda : session_manager.get_session()['valid']
run(app, host="0.0.0.0", port=8080, debug=True, reloader=True)
