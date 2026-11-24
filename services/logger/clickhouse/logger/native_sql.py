"""Pure opt-in native ingestion SQL; no broker, key-file or database I/O."""

DURABLES = {name: 'puda_native_' + name.lower() for name in ('RESPONSE_QUEUE', 'RESPONSE_IMMEDIATE')}


def validate_settings(server, key_path, named_collection=None):
    """Validate native endpoint/path without constructing DDL or doing I/O."""
    from urllib.parse import urlsplit
    u = urlsplit(server)
    import re
    if named_collection is not None and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', named_collection):
        raise ValueError('Invalid named collection')
    secure = named_collection is not None and u.scheme == 'tls' and bool(u.hostname)
    local = named_collection is None and u.scheme == 'nats' and u.hostname == '127.0.0.1'
    if not (secure or local) or not u.port or u.username or u.password or u.path or u.query or u.fragment:
        raise ValueError('Use TLS with a named collection, or explicit loopback NATS')
    validate_key_path(key_path)


def validate_key_path(key_path):
    import re
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(key_path)):
        raise ValueError('Unsafe dictionary path')


def key_statements(key_path):
    """Secret dictionary setup, independent of NATS sources/views."""
    validate_key_path(key_path)
    yield 'CREATE DATABASE IF NOT EXISTS puda_native_secrets'
    yield f"""CREATE DICTIONARY puda_native_secrets.keys (kid String, key_hex String)
        PRIMARY KEY kid SOURCE(FILE(PATH '{key_path}' FORMAT 'TabSeparated'))
        LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(0)"""


def statements(server, key_path='/var/lib/clickhouse/user_files/puda-keys.tsv', named_collection=None):
    """DDL for a credential-free loopback endpoint (deployment opt-in)."""
    validate_settings(server, key_path, named_collection)
    engine = f'NATS({named_collection})' if named_collection else 'NATS'
    endpoint = '' if named_collection else f"nats_url='{server}', "
    yield from key_statements(key_path)
    for suffix in ('queue', 'immediate'):
        name = 'native_response_' + suffix
        yield f"""CREATE TABLE puda.{name} (payload String) ENGINE={engine}
            SETTINGS {endpoint}nats_subjects='puda.*.cmd.response.{suffix}',
            nats_stream='RESPONSE_{suffix.upper()}', nats_consumer_name='{DURABLES['RESPONSE_' + suffix.upper()]}',
            nats_format='RawBLOB', nats_max_block_size=1, nats_flush_interval_ms=100,
            nats_skip_broken_messages=0, nats_commit_on_select=0"""
        yield command_view(name, 'response')
    for name, subject, kind in (
        ('native_command_queue', 'puda.*.cmd.queue', 'command'),
        ('native_command_immediate', 'puda.*.cmd.immediate', 'command'),
        ('native_health', 'puda.*.tlm.health', 'telemetry'),
        ('native_stream', 'puda.*.tlm.stream.>', 'telemetry_stream'),
    ):
        yield f"""CREATE TABLE puda.{name} (payload String) ENGINE={engine}
            SETTINGS {endpoint}nats_subjects='{subject}',
            nats_queue_group='puda_native_core', nats_format='RawBLOB',
            nats_max_block_size=1, nats_flush_interval_ms=100,
            nats_skip_broken_messages=0, nats_commit_on_select=0"""
        yield command_view(name, kind) if kind == 'command' else telemetry_view(name, kind)


def last_object(source):
    """Match Python json.loads: the last duplicate object member wins."""
    pairs = f'JSONExtractKeysAndValuesRaw({source})'
    return f"concat('{{',arrayStringConcat(arrayMap(k -> concat(toJSONString(k),':',arrayLast(x -> x.1=k,{pairs}).2),arrayDistinct(JSONExtractKeys({source}))),','),'}}')"


def decrypt_with():
    return f"""WITH hex(substring(payload,3,4)) AS kid,
      unhex(dictGetOrDefault('puda_native_secrets.keys','key_hex',tuple(kid),'')) AS secret,
      tryDecrypt('aes-256-gcm',substring(payload,19),if(length(secret)=32,secret,repeat('0',32)),substring(payload,7,12),_subject) AS clear,
      if(throwIf(length(payload)<34 OR substring(payload,1,2)!=unhex('E201') OR length(secret)!=32 OR hex(substring(SHA256(secret),1,4))!=kid OR isNull(clear), 'Native E2EE rejected')=0,ifNull(clear,''),'') AS plaintext,
      if(throwIf(NOT isValidUTF8(plaintext) OR NOT isValidJSON(plaintext) OR JSONType(plaintext)!='Object', 'Native JSON rejected')=0,plaintext,'') AS raw_json,
      {last_object('raw_json')} AS doc"""


def timestamp_expression(source):
    raw = f"JSONExtractRaw({source},'timestamp')"
    ts = f"JSONExtractString({source},'timestamp')"
    # Validate the original fields: the best-effort parser normalizes invalid
    # clocks and zero month/day values instead of rejecting them.
    pattern = '[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,9})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])'
    year = f"toUInt32OrZero(substring({ts},1,4))"
    month = f"toUInt32OrZero(substring({ts},6,2))"
    day = f"toUInt32OrZero(substring({ts},9,2))"
    leap = f"({year}%4=0 AND ({year}%100!=0 OR {year}%400=0))"
    days = f"multiIf({month}=2,28+{leap},{month} IN (4,6,9,11),30,31)"
    # Parse whole seconds and accumulate in Int128 before checking Int64 bounds.
    # Parsing directly at scale 9 can overflow before the range check. Preserve
    # the original fractional digits independently, including timezone offsets.
    parsed = f"parseDateTime64BestEffortOrNull({ts},0,'UTC')"
    fraction = f"toInt128OrZero(rightPad(extract({ts},'[.]([0-9]+)'),9,'0'))"
    ns = f"(toInt128(ifNull(toUnixTimestamp64Milli({parsed}),-1))*1000000+{fraction})"
    return f"""if({raw} IN ('','null'),toUnixTimestamp64Nano(now64(9)),
        if(throwIf(NOT match({ts},'^{pattern}$') OR {year}<1969 OR {year}>2262 OR
          {day}>{days} OR isNull({parsed}) OR {ns}<0 OR {ns}>9223372036854775807,
          'Native timestamp rejected')=0,toInt64({ns}),0))"""


def command_select(source, kind):
    """Build a SELECT from a trusted SQL relation (not untrusted input)."""
    status = "JSONExtractString(r,'status')" if kind == 'response' else "'sent'"
    invalid = ["JSONType(raw_json)!='Object'", "JSONType(h)!='Object'", "JSONType(c)!='Object'",
        "JSONType(h,'machine_id')!='String'", "JSONType(c,'name')!='String'", "NOT JSONHas(h,'timestamp')"]
    invalid += [f"JSONType(h,'{field}') NOT IN ('String','Null')" for field in ('run_id','username','user_id')]
    invalid += ["JSONType(c,'version') NOT IN ('String','Null')"]
    if kind == 'response':
        invalid += ["JSONType(doc,'response')!='Object'", "JSONType(r,'status')!='String'"]
    guard = ' OR '.join(invalid)
    return f"""    {decrypt_with()},
      {last_object("JSONExtractRaw(doc,'header')")} AS h,
      {last_object("JSONExtractRaw(doc,'command')")} AS c,
      {last_object("JSONExtractRaw(doc,'response')")} AS r
    SELECT lower(hex(SHA256(concat(_subject,char(0),raw_json)))) AS event_id,
      {timestamp_expression('h')} AS event_ns,
      toUnixTimestamp64Nano(now64(9)) AS received_ns, _subject AS subject,
      if(throwIf({guard},'Native command rejected')=0,JSONExtractString(h,'machine_id'),'') AS machine_id, JSONExtractString(h,'run_id') AS run_id,
      '{kind}' AS msg_type, arrayStringConcat(arraySlice(splitByChar('.',_subject),4),'.') AS topic,
      JSONExtractString(c,'name') AS cmd_name,
      if(throwIf(JSONType(c,'step_number') NOT IN ('Int64','UInt64') OR isNull(toInt64OrNull(JSONExtractRaw(c,'step_number'))), 'Native command rejected')=0,JSONExtractInt(c,'step_number'),0) AS step_number,
      JSONExtractString(h,'username') AS username, JSONExtractString(h,'user_id') AS user_id,
      JSONExtractString(c,'version') AS cmd_version, {status} AS status,
      raw_json FROM {source}"""


def telemetry_select(source, kind):
    """Build a SELECT from a trusted SQL relation (not untrusted input)."""
    stream = "'health'" if kind == 'telemetry' else "arrayStringConcat(arraySlice(splitByChar('.',_subject),5),'.')"
    return f"""    {decrypt_with()},
      JSONExtractKeysAndValuesRaw(doc) AS pairs
    SELECT lower(hex(SHA256(concat(_subject,char(0),raw_json)))) AS event_id,
      {timestamp_expression('doc')} AS event_ns,
      toUnixTimestamp64Nano(now64(9)) AS received_ns, _subject AS subject,
      splitByChar('.',_subject)[2] AS machine_id, '{kind}' AS msg_type,
      arrayStringConcat(arraySlice(splitByChar('.',_subject),4),'.') AS topic,
      {stream} AS stream,
      if(arraySort(JSONExtractKeys(doc))=['data','timestamp'] AND JSONType(doc,'data')='Object',
        JSONExtractRaw(doc,'data'), concat('{{',arrayStringConcat(arrayMap(x -> concat(toJSONString(x.1),':',x.2),arrayFilter(x -> x.1!='timestamp',pairs)),','),'}}')) AS data,
      raw_json FROM {source}"""


def command_view(name, kind):
    return f"CREATE MATERIALIZED VIEW puda.{name}_mv TO puda.command_logs AS\n" + command_select(f'puda.{name}', kind)


def telemetry_view(name, kind):
    return f"CREATE MATERIALIZED VIEW puda.{name}_mv TO puda.telemetry AS\n" + telemetry_select(f'puda.{name}', kind)
