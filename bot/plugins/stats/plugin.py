import logging
import re
from io import BytesIO, StringIO

from discord.enums import Status
from django.core.files import File
from django.db.models import Count, Q
from django.utils.timesince import timesince
from django.utils.timezone import make_aware, now, utc
from import_export.admin import DEFAULT_FORMATS
from tabulate import tabulate

from bot.channels.models import Channel
from bot.games.models import Game
from bot.plugins.base import BasePlugin
from bot.plugins.commands import command
from bot.users.models import Member

from .models import Download, GameSession, LoggedMessage
from .resources import GamesPlayedResource

logger = logging.getLogger(__name__)


EXPORT_FORMATS = {f().get_title(): f for f in DEFAULT_FORMATS if f().can_export()}


class Plugin(BasePlugin):

    has_blocking_io = True

    async def on_message(self, message):
        """
        Log the message in the db
        """
        await super().on_message(message)

        if message.channel.is_private:
            return

        member = Member.objects.from_message(message)
        channel = Channel.objects.from_message(message)

        n_lines = len(message.content.splitlines())

        logged_message = LoggedMessage.objects.create(
            server=message.server.id,
            discord_id=message.id, member=member,
            member_username=message.author.name,
            channel=channel, content=message.content,
            num_lines=n_lines
        )
        if message.mentions:
            logged_message.mentions.set(
                Member.objects.from_mentions(message.mentions)
            )

    async def on_message_edit(self, before, after):
        await super().on_message_edit(before, after)

        logged_message = LoggedMessage.objects.filter(discord_id=before.id).first()
        if not logged_message:
            return

        if after is not None:
            if after.edited_timestamp:
                logged_message.edited_timestamp = make_aware(after.edited_timestamp, utc)
            logged_message.content = after.content
            logged_message.num_lines = len(after.content.splitlines())
            logged_message.save()

    async def on_member_update(self, before, after):
        if hasattr(super(), 'on_member_update'):
            await super().on_member_update(before, after)

        member = Member.objects.from_discord(after)
        server = after.server.id

        if before.status != after.status and after.status != Status.online:
            member.last_seen = now()
            member.save()

        # nothing game wise has changed - abort
        if not before.game and not after.game:
            return

        # if no status was set before, and there is one after, a game was started
        started_session = before.game is None and after.game is not None
        # if no status is set after, but there was one before, a game was stopped
        stopped_session = before.game is not None and after.game is None

        changed_session = (
            not (started_session or stopped_session)
            and before.game.name != after.game.name  # noqa
        )

        if started_session:
            GameSession.objects.start(after.game, member, server)
        else:
            last_session = GameSession.objects.last_session_for_member(member, server)
            game = Game.objects.get_by_name(before.game.name)

            if stopped_session or changed_session:
                if last_session and last_session.game == game:
                    last_session.stop_session()

            if changed_session:
                GameSession.objects.start(after.game, member, server)

    @command(help='Show the top 10 posters')
    async def stat_messages(self, command):
        await command.send_typing()
        server_id = command.message.server.id
        queryset = (
            Member.objects
            .exclude(is_bot=True)
            .annotate(num_messages=Count(
                'messages_authored',
                filter=Q(messages_authored__server=server_id)
            ))
        )
        top_10 = queryset.order_by('-num_messages')[:10]
        data = [(member.name or str(member), member.num_messages) for member in top_10]
        output = tabulate(data, headers=('User', 'Messages'))
        await command.reply("```\n{}\n```".format(output))

    @command(pattern=re.compile(r'(?P<name>.*)', re.IGNORECASE))
    async def seen(self, command):
        if command.message.mentions:
            if len(command.message.mentions) > 1:
                await command.reply('Supply one user at a time')
                return
            d_member = command.message.mentions[0]
            member = Member.objects.filter(discord_id=d_member.id).first()
            username = d_member.name
        else:
            username = command.args.name
            member = Member.objects.filter(name__iexact=username).first()
            all_members = command.message.channel.server.members
            d_member = next((m for m in all_members if m.name.lower() == username.lower()), None)

        if d_member and d_member.status == Status.online:
            await command.reply('{} is currently online'.format(d_member.name))
            if member:
                member.last_seen = now()
                member.save()
            return

        if not member or not member.last_seen:
            await command.reply('Haven\'t seen {} (yet)'.format(username))
            return

        if member:
            last_message = member.messages_authored.latest('timestamp')
            reply1 = "{name} was last seen: {last_seen} ago".format(
                name=username,
                last_seen=timesince(member.last_seen)
            )
            reply2 = "The last message was: ```{message}```".format(message=last_message.content)
            await command.reply("{}\n{}".format(reply1, reply2))

    @command(help='Shows the most popular games in total play time')
    async def stat_games(self, command):
        await command.send_typing()
        server_id = command.message.server.id
        data = get_game_time(server=server_id)
        await command.reply("```\n{}\n```".format(
            tabulate(data, headers=('Game', 'Time')))
        )

    @command(help='Show my game time, registered through the discord status')
    async def stat_my_games(self, command):
        await command.send_typing()
        server_id = command.message.server.id
        member_id = command.message.author.id
        data = get_game_time(server=server_id, member_id=member_id)
        await command.reply("```\n{}\n```".format(
            tabulate(data, headers=('Game', 'Time')))
        )

    @command(
        pattern=re.compile(r'(?P<format>{})?'.format(
            '|'.join(EXPORT_FORMATS.keys())
        ), re.IGNORECASE),
        help='Exports the unformatted games stats to CSV')
    async def export_stat_games(self, command):
        await command.reply('Generating file...')
        file_format = EXPORT_FORMATS[command.args.format or 'csv']()
        resource = GamesPlayedResource()
        dataset = resource.export(GameSession.objects.get_game_durations())
        export_data = file_format.export_data(dataset)
        if file_format.is_binary():
            _file = BytesIO(export_data)
        else:
            _file = StringIO(export_data)

        download = Download.objects.create(title='Games playtime')
        filename = '{}.{}'.format(command.command.name, file_format.get_extension())
        download.file.save(filename, File(_file))
        await command.reply('Download the file at {}'.format(download.file.url))


def format_delta(delta):
    hours, seconds = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    min_minutes = not hours and not delta.days
    minutes = max(1, minutes) if min_minutes else minutes
    return f"{delta.days} days, {hours} hours, {minutes} minutes"


def get_game_time(server: str, member_id: str = None) -> list:
    games = (
        GameSession.objects.filter(server=server)
        .get_game_durations(member_id=member_id)
    )[:15]

    data = [
        (game['game__name'], format_delta(game['time']))
        for game in games
    ]
    return data
