import json
import logging
import os
import sys
from unittest import mock

import pytest
from click.testing import CliRunner

from pinhook import log
from pinhook.bot import Bot, TwitchBot
from pinhook.cli import Config, cli


def run_cli(tmp_path, config, name='config.json'):
    path = tmp_path / name
    path.write_text(config if isinstance(config, str) else json.dumps(config))
    with mock.patch('pinhook.cli.Bot') as bot:
        result = CliRunner().invoke(cli, ['run', str(path)])
    return result, bot


BASE = {'nickname': 'pinbot', 'server': 'localhost', 'channels': ['#test']}


@pytest.fixture(autouse=True)
def no_secrets(monkeypatch):
    # what one test's config hid would be masked in the next test's output
    monkeypatch.setattr(log, 'secrets', set())


def test_config_schema_knows_every_bot_option():
    assert set(Config().fields) - {'nickname', 'channels', 'server', 'platform', 'token'} \
        == Bot.options


def test_every_twitch_bot_option_is_in_the_schema():
    assert TwitchBot.options <= set(Config().fields)


def test_quoted_booleans_in_config_become_real_booleans(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, bot_mode='false', ssl_verify='false'))
    assert result.exit_code == 0
    assert bot.call_args.kwargs['bot_mode'] is False
    assert bot.call_args.kwargs['ssl_verify'] is False


def test_unknown_config_keys_are_passed_to_bot(tmp_path):
    # Bot warns about them, so the CLI should not drop them silently
    result, bot = run_cli(tmp_path, dict(BASE, ssl_requred=True))
    assert bot.call_args.kwargs['ssl_requred'] is True


def test_toml_configs_are_refused_with_what_to_do(tmp_path):
    result, bot = run_cli(tmp_path, 'nickname = "pinbot"\n', name='config.toml')
    assert result.exit_code != 0
    assert 'is TOML, which pinhook 2.0 no longer reads' in result.output
    bot.assert_not_called()


def test_yaml_that_would_run_code_is_refused(tmp_path):
    config = 'nickname: !!python/object/apply:os.getcwd []\nserver: x\nchannels: ["#t"]\n'
    result, bot = run_cli(tmp_path, config, name='config.yaml')
    assert result.exit_code == 1
    assert "isn't valid YAML, or holds something configs don't allow" in result.output
    bot.assert_not_called()


def test_a_config_with_no_command_runs_the_bot_with_a_warning(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(BASE))
    with mock.patch('pinhook.cli.Bot') as bot:
        result = CliRunner().invoke(cli, [str(path)])
    assert result.exit_code == 0, result.output
    assert bot.call_args.kwargs['nickname'] == 'pinbot'
    bot.return_value.start.assert_called_once()
    assert "'pinhook {0}' is shorthand for 'pinhook run {0}'".format(path) in result.output
    assert 'will be deprecated in a future version' in result.output


def test_no_arguments_lists_the_commands():
    result = CliRunner().invoke(cli, [])
    assert 'run' in result.output and 'Run, check and create pinhook bots.' in result.output


def test_config_mistakes_are_listed_without_traceback(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, port='sixsixsixseven', log_level='verbose'))
    assert result.exit_code != 0
    assert 'has problems:' in result.output
    assert 'port: Not a valid integer.' in result.output
    assert 'log_level: Must be one of' in result.output
    assert 'Traceback' not in result.output


def test_bot_startup_errors_are_shown_plainly(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(BASE))
    error = ValueError("couldn't read ban file bans.json: oops")
    with mock.patch('pinhook.cli.Bot', side_effect=error):
        result = CliRunner().invoke(cli, ['run', str(path)])
    assert result.exit_code != 0
    assert "Error: couldn't read ban file bans.json: oops" in result.output


def test_environment_variables_are_filled_in(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_NS_PASS', 'hunter2')
    monkeypatch.setenv('PH_CHAN', 'games')
    config = dict(BASE, ns_pass='${PH_NS_PASS}', channels=['#${PH_CHAN}', '#chat'])
    result, bot = run_cli(tmp_path, config)
    assert result.exit_code == 0, result.output
    assert bot.call_args.kwargs['ns_pass'] == 'hunter2'
    assert bot.call_args.kwargs['channels'] == ['#games', '#chat']


def test_missing_environment_variable_stops_with_its_name(tmp_path, monkeypatch):
    monkeypatch.delenv('PH_MISSING', raising=False)
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='${PH_MISSING}'))
    assert result.exit_code != 0
    assert "uses ${PH_MISSING}, but that environment variable isn't set" in result.output
    bot.assert_not_called()


def test_double_dollar_is_a_literal(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_NS_PASS', 'nope')
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='pa$${PH_NS_PASS}ss'))
    assert bot.call_args.kwargs['ns_pass'] == 'pa${PH_NS_PASS}ss'


def test_environment_variables_work_in_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_SERVER', 'irc.libera.chat')
    config = 'nickname: pinbot\nserver: "${PH_SERVER}"\nchannels: ["#test"]\n'
    result, bot = run_cli(tmp_path, config, name='config.yaml')
    assert bot.call_args.kwargs['server'] == 'irc.libera.chat'


def test_plugin_config_is_passed_to_the_bot_with_environment_variables(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_WEATHER_KEY', 'abc123')
    weather = {'api_key': '${PH_WEATHER_KEY}', 'units': 'metric'}
    result, bot = run_cli(tmp_path, dict(BASE, plugin_config={'weather': weather}))
    assert result.exit_code == 0, result.output
    expected = {'weather': {'api_key': 'abc123', 'units': 'metric'}}
    assert bot.call_args.kwargs['plugin_config'] == expected


def test_plugin_config_sections_must_be_mappings(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, plugin_config={'weather': ['not', 'a', 'mapping']}))
    assert result.exit_code != 0
    assert 'plugin_config.weather: Not a valid mapping type.' in result.output
    assert 'defaultdict' not in result.output


def test_unquoted_channel_names_in_a_flow_list_say_to_quote_them(tmp_path):
    config = 'nickname: pinbot\nserver: x\nchannels: [#games, #chat]\n'
    result, bot = run_cli(tmp_path, config, name='config.yaml')
    assert result.exit_code == 1
    assert "a channel name isn't quoted, so YAML read it as a comment" in result.output
    bot.assert_not_called()


def test_unquoted_channel_names_in_a_block_list_say_to_quote_them(tmp_path):
    config = ("nickname: pinbot\nserver: x\nchannels:\n  - #games\n  - '#chat'\n"
              "plugin_channels:\n  dice: #games\n")
    result, bot = run_cli(tmp_path, config, name='config.yaml')
    assert result.exit_code == 1
    assert "  channels: a channel name isn't quoted" in result.output
    assert "  plugin_channels.dice: a channel name isn't quoted" in result.output
    bot.assert_not_called()


def test_a_nick_yaml_reads_as_a_boolean_says_to_quote_it(tmp_path):
    config = "nickname: off\nserver: x\nchannels: ['#games']\nops:\n  - yes\n"
    result, bot = run_cli(tmp_path, config, name='config.yaml')
    assert result.exit_code == 1
    assert "nickname: YAML read off as false, not a name. Quote it, like nickname: 'off'" \
        in result.output
    assert 'ops: YAML read an op as true or false' in result.output
    bot.assert_not_called()


def test_quoted_names_are_fine(tmp_path):
    config = "nickname: 'off'\nserver: x\nchannels: ['#games']  # the main one\n"
    result, bot = run_cli(tmp_path, config, name='config.yaml')
    assert result.exit_code == 0, result.output
    assert bot.call_args.kwargs['channels'] == ['#games']


GOOD_PLUGIN = '''from pinhook import Plugin, command


class Hello(Plugin):
    def setup(self, previous):
        self.ready = True

    def teardown(self):
        open(__file__ + '.teardown', 'w').close()

    @command('hello')
    async def hello(self, ctx):
        await ctx.reply('hi')
'''


def bot_folder(tmp_path, config, plugins=None, recipes=None):
    for folder, files in (('plugins', plugins or {}), ('recipes', recipes or {})):
        (tmp_path / folder).mkdir()
        for name, text in files.items():
            (tmp_path / folder / name).write_text(text)
    path = tmp_path / 'config.yaml'
    path.write_text("nickname: 'pinbot'\nserver: 'localhost'\nchannels: ['#test']\n"
                    "bot_dir: '{}'\n{}".format(tmp_path, config))
    return path


def check(path):
    return CliRunner().invoke(cli, ['check', str(path)])


def test_check_says_what_it_loaded(tmp_path):
    path = bot_folder(tmp_path, '', plugins={'hello.py': GOOD_PLUGIN},
                      recipes={'hug.yaml': "version: 1\nsteps:\n  - reply: '{nick} hugs'\n"})
    result = check(path)
    assert result.exit_code == 0, result.output
    assert result.output == ('{} is fine. Loaded 1 plugin with 1 command, and 1 recipe\n'
                             .format(path))
    # setup ran when the plugin loaded, and teardown before check finished
    assert (tmp_path / 'plugins' / 'hello.py.teardown').exists()
    # nothing was logged to a file
    assert not (tmp_path / 'logs').exists()


def test_check_lists_warnings_and_still_passes(tmp_path):
    path = bot_folder(tmp_path, 'ssl_requred: true\n', recipes={
        'games.yaml': "version: 1\nsteps:\n  - reply: '{store.game}'\n"})
    result = check(path)
    assert result.exit_code == 0, result.output
    assert "warning: unknown option 'ssl_requred' ignored, did you mean 'ssl_required'?" \
        in result.output
    assert 'warning: games reads store.game, which no recipe sets' in result.output
    assert 'has 2 warnings. Loaded 0 plugins with 0 commands, and 1 recipe' in result.output


def test_check_fails_on_a_plugin_or_recipe_that_cant_load(tmp_path):
    path = bot_folder(tmp_path, '', plugins={'broken.py': 'def oops(:\n'},
                      recipes={'bad.yaml': "version: 1\nsteps:\n  - reply: '{nope}'\n"})
    result = check(path)
    assert result.exit_code == 1
    assert 'error: could not load plugin broken: SyntaxError' in result.output
    assert "{nope} isn't set by this point" in result.output
    assert 'has 2 errors and 0 warnings' in result.output
    assert 'Traceback' not in result.output


def test_check_stops_at_config_problems(tmp_path):
    path = bot_folder(tmp_path, "port: 'sixsixsixseven'\n")
    result = check(path)
    assert result.exit_code == 1
    assert 'port: Not a valid integer.' in result.output


def test_file_secrets_are_read_without_their_last_line_break(tmp_path):
    (tmp_path / 'secrets').mkdir()
    (tmp_path / 'secrets' / 'ns_pass').write_text('hunter2\n')
    absolute = tmp_path / 'server_pass'
    absolute.write_text('swordfish')
    config = dict(BASE, ns_pass='${file:secrets/ns_pass}', server_pass='${file:%s}' % absolute)
    result, bot = run_cli(tmp_path, config)
    assert result.exit_code == 0, result.output
    assert bot.call_args.kwargs['ns_pass'] == 'hunter2'
    assert bot.call_args.kwargs['server_pass'] == 'swordfish'


def test_a_missing_file_secret_names_the_file(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='${file:/run/secrets/nope}'))
    assert result.exit_code == 1
    assert "uses ${file:/run/secrets/nope}, but it can't be read: No such file or directory" \
        in result.output
    bot.assert_not_called()


def secrets_env(tmp_path, monkeypatch, text, mode=0o600):
    # a copy of the environment, so what secrets.env sets goes away after the test
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    path = tmp_path / 'secrets.env'
    path.write_text(text)
    path.chmod(mode)
    return path


def test_secrets_env_beside_the_config_is_read(tmp_path, monkeypatch):
    secrets_env(tmp_path, monkeypatch, '# for pinbot\n\nPH_NS_PASS=hunter2\n'
                                       'export PH_SERVER_PASS="sword fish"\n')
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='${PH_NS_PASS}',
                                         server_pass='${PH_SERVER_PASS}'))
    assert result.exit_code == 0, result.output
    assert bot.call_args.kwargs['ns_pass'] == 'hunter2'
    assert bot.call_args.kwargs['server_pass'] == 'sword fish'
    assert 'warning' not in result.output


def test_the_environment_wins_over_secrets_env(tmp_path, monkeypatch):
    secrets_env(tmp_path, monkeypatch, 'PH_NS_PASS=from-the-file\n')
    os.environ['PH_NS_PASS'] = 'from-the-environment'
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='${PH_NS_PASS}'))
    assert bot.call_args.kwargs['ns_pass'] == 'from-the-environment'


def test_a_secrets_env_others_can_read_is_warned_about(tmp_path, monkeypatch):
    path = secrets_env(tmp_path, monkeypatch, 'PH_NS_PASS=hunter2\n', mode=0o644)
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='${PH_NS_PASS}'))
    assert result.exit_code == 0
    assert 'warning: other users can read {0}. Make it yours only: chmod 600 {0}'.format(path) \
        in result.output


def test_a_bad_secrets_env_line_is_named_without_showing_it(tmp_path, monkeypatch):
    path = secrets_env(tmp_path, monkeypatch, 'PH_A=1\nhunter2\n')
    result, bot = run_cli(tmp_path, BASE)
    assert result.exit_code == 1
    assert '{} line 2 should be NAME=value'.format(path) in result.output
    assert 'hunter2' not in result.output
    bot.assert_not_called()


def test_secret_settings_and_plugin_config_are_masked_in_the_log(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_NS_PASS', 'hunter2')
    monkeypatch.setenv('PH_WEATHER_KEY', 'weather-key-123')
    monkeypatch.setenv('PH_CHAN', 'games')
    (tmp_path / 'token').write_text('oauth-abc123\n')
    run_cli(tmp_path, dict(BASE, ns_pass='${PH_NS_PASS}', server_pass='${file:token}',
                           channels=['#${PH_CHAN}'],
                           plugin_config={'weather': {'key': '${PH_WEATHER_KEY}'}}))
    record = logging.LogRecord('bot.pinbot', logging.ERROR, __file__, 1,
                               'login failed for hunter2 with %s, %s, in #games',
                               ('oauth-abc123', 'weather-key-123'), None)
    line = log.formatter.format(record)
    # a channel from the environment isn't a secret, so it stays readable
    assert line.endswith('login failed for *** with ***, ***, in #games')


def test_masking_covers_tracebacks():
    log.hide('hunter2')
    try:
        raise ValueError('bad password hunter2')
    except ValueError:
        record = logging.LogRecord('bot', logging.ERROR, __file__, 1, 'oops', (),
                                   sys.exc_info())
    assert 'hunter2' not in log.formatter.format(record)
    assert 'ValueError: bad password ***' in log.formatter.format(record)


TWITCH = {'platform': 'twitch', 'nickname': 'gamebot', 'channels': ['#mychannel']}


def run_twitch(tmp_path, config):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    with mock.patch('pinhook.cli.TwitchBot') as bot:
        result = CliRunner().invoke(cli, ['run', str(path)])
    return result, bot


def test_platform_twitch_runs_a_twitch_bot(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_TWITCH_TOKEN', 'oauth:abc123def')
    result, bot = run_twitch(tmp_path, dict(TWITCH, token='${PH_TWITCH_TOKEN}', ops=['mal']))
    assert result.exit_code == 0, result.output
    assert bot.call_args.args == ('gamebot', '#mychannel', 'abc123def')
    assert bot.call_args.kwargs == {'ops': ['mal'], 'config_dir': str(tmp_path)}
    bot.return_value.start.assert_called_once()


def test_a_twitch_bot_needs_a_token_and_one_channel(tmp_path):
    result, bot = run_twitch(tmp_path, dict(TWITCH, channels=['#a', '#b']))
    assert result.exit_code == 1
    assert "token: a Twitch bot needs the bot account's oauth token" in result.output
    bot.assert_not_called()
    result, bot = run_twitch(tmp_path, dict(TWITCH, token='abc', channels=['#a', '#b']))
    assert 'channels: a Twitch bot joins one channel in pinhook 2.0' in result.output


def test_an_irc_bot_still_needs_a_server(tmp_path):
    result, bot = run_cli(tmp_path, {'nickname': 'pinbot', 'channels': ['#test']})
    assert result.exit_code == 1
    assert 'server: Missing data for required field.' in result.output


def test_an_unknown_platform_is_refused(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, platform='slack'))
    assert 'platform: Must be one of: irc, twitch.' in result.output


def test_check_works_on_a_twitch_config(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text("platform: twitch\nnickname: 'gamebot'\nchannels: ['#mychannel']\n"
                    "token: 'abc'\nbot_dir: '{}'\nssl_required: true\n".format(tmp_path))
    result = CliRunner().invoke(cli, ['check', str(path)])
    assert result.exit_code == 0, result.output
    assert "warning: unknown option 'ssl_required' ignored" in result.output


def test_pinhook_variables_set_options_the_config_leaves_out(tmp_path, monkeypatch):
    monkeypatch.setenv('PINHOOK_LOG_FILE', '-')
    monkeypatch.setenv('PINHOOK_HEALTH_PORT', '8080')
    monkeypatch.setenv('PINHOOK_SSL_REQUIRED', 'true')
    monkeypatch.setenv('PINHOOK_BOT_DIR', '/bot')
    monkeypatch.setenv('PINHOOK_SASL_PASSWORD', 'hunter2')
    monkeypatch.setenv('PINHOOK_CHANNELS', '#nope')
    result, bot = run_cli(tmp_path, dict(BASE, bot_dir='/srv/bot'))
    assert result.exit_code == 0, result.output
    options = bot.call_args.kwargs
    assert options['log_file'] == '-'
    assert options['health_port'] == 8080
    assert options['ssl_required'] is True
    # the config wins, secrets only come from ${...}, and lists can't be set this way
    assert options['bot_dir'] == '/srv/bot'
    assert 'sasl_password' not in options
    assert options['channels'] == ['#test']


def test_a_bad_pinhook_variable_is_named_like_a_config_problem(tmp_path, monkeypatch):
    monkeypatch.setenv('PINHOOK_HEALTH_PORT', 'eighty')
    result, bot = run_cli(tmp_path, BASE)
    assert result.exit_code == 1
    assert 'health_port: Not a valid integer.' in result.output


def test_relative_paths_start_from_the_config_file(tmp_path, monkeypatch):
    (tmp_path / 'gamebot' / 'plugins').mkdir(parents=True)
    (tmp_path / 'gamebot' / 'plugins' / 'hello.py').write_text(GOOD_PLUGIN)
    (tmp_path / 'gamebot' / 'config.yaml').write_text(
        "nickname: 'pinbot'\nserver: 'localhost'\nchannels: ['#test']\nbot_dir: '.'\n")
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = CliRunner().invoke(cli, ['check', '../gamebot/config.yaml'])
    assert result.exit_code == 0, result.output
    assert 'Loaded 1 plugin with 1 command' in result.output


def test_without_bot_dir_paths_start_from_the_config_file_too(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, plugin_dir='my_plugins'))
    assert bot.call_args.kwargs['config_dir'] == str(tmp_path)
    real = Bot(['#test'], 'pinbot', 'localhost', plugin_dir='my_plugins', log_file=os.devnull,
               config_dir=str(tmp_path))
    assert real.plugin_dir == str(tmp_path / 'my_plugins')
    assert real.data_dir == str(tmp_path / 'data')
