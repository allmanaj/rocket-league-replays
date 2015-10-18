from django import template
from django.db.models import Count, F, Q, Sum, Max
from django.utils.safestring import mark_safe

from ..models import Replay, Goal, Player

register = template.Library()


@register.assignment_tag
def get_replay_by_pk(pk):
    try:
        return Replay.objects.get(pk=pk)
    except Replay.DoesNotExist:
        return None


@register.inclusion_tag('replays/includes/scoreboard.html', takes_context=True)
def scoreboard(context, team):
    return {
        'players': context['replay'].player_set.filter(
            team=team,
        ),
        'team': team,
        'team_str': 'Blue' if team == 0 else 'Orange'
    }


@register.assignment_tag
def steam_stats(uid):
    data = {}

    # Winning goals scored.
    data['winning_goals'] = Goal.objects.filter(
        player__platform='OnlinePlatform_Steam',
        player__online_id=uid,
        replay__show_leaderboard=True,
        number=F('replay__team_0_score') + F('replay__team_1_score')
    ).count()

    # Last minute goals (literally, goals scored within the last minute of the game)
    data['last_minute_goals'] = Goal.objects.filter(
        player__platform='OnlinePlatform_Steam',
        player__online_id=uid,
        replay__show_leaderboard=True,
        frame__gte=F('replay__num_frames') - (60 * F('replay__record_fps'))
    ).count()

    # Number of times the player has scored a goal which equalised the game and
    # forced it into overtime.
    data['overtime_triggering_goals'] = 0
    data['overtime_triggering_and_winning_goals'] = 0
    data['overtime_trigger_and_team_win'] = 0

    # Find replays which went into overtime.
    replays = Replay.objects.filter(
        show_leaderboard=True,
        goal__frame__gte=(60 * 5 * F('record_fps')),
    )

    # Get all games with overtime goals.
    replays = Replay.objects.annotate(
        num_goals=F('team_0_score') + F('team_1_score'),
    ).filter(
        num_frames__gt=60 * 5 * F('record_fps'),
        show_leaderboard=True,
        player__platform='OnlinePlatform_Steam',
        player__online_id=uid,
        num_goals__gte=2,
    ).prefetch_related('goal_set')

    for replay in replays:
        # Who scored the 2nd to last goal?
        try:
            goal = replay.goal_set.get(
                number=replay.num_goals - 1,
                player__platform='OnlinePlatform_Steam',
                player__online_id=uid,
            )

            data['overtime_triggering_goals'] += 1

            # Did the team win?
            team = goal.player.team

            if (
                team == 0 and replay.team_0_score > replay.team_1_score or
                team == 1 and replay.team_1_score > replay.team_0_score
            ):
                data['overtime_trigger_and_team_win'] += 1

            # Did they also score the winning goal?
            replay.goal_set.get(
                number=replay.num_goals,
                player__platform='OnlinePlatform_Steam',
                player__online_id=uid,
            )

            data['overtime_triggering_and_winning_goals'] += 1
        except Goal.DoesNotExist:
            pass

    # Which match size does this player appear most in?
    data['preferred_match_size'] = None

    sizes = Replay.objects.filter(
        show_leaderboard=True,
        player__platform='OnlinePlatform_Steam',
        player__online_id=uid,
    ).values('team_sizes').annotate(
        Count('team_sizes'),
    ).order_by('-team_sizes__count')

    if len(sizes) > 0:
        data['preferred_match_size'] = sizes[0]['team_sizes']

    # What's this player's prefered role within a team?
    data['preferred_role'] = None

    role_query = Player.objects.filter(
        replay__show_leaderboard=True,
        platform='OnlinePlatform_Steam',
        online_id=uid,
    ).aggregate(
        goals=Sum('goals'),
        assists=Sum('assists'),
        saves=Sum('saves'),
    )

    max_stat = max(role_query, key=lambda k: role_query[k])

    if max_stat == 'goals':
        data['preferred_role'] = 'Goalscorer'
    elif max_stat == 'assists':
        data['preferred_role'] = 'Assister'
    elif max_stat == 'saves':
        data['preferred_role'] = 'Goalkeeper'

    # Number of times the player's score was higher than everyone else on their
    # team put together.
    data['carries'] = 0

    # Number of times the player's score was higher than everyone else put together.
    data['dominations'] = 0

    replays = Replay.objects.filter(
        team_sizes__gte=2,
        show_leaderboard=True,
        player__platform='OnlinePlatform_Steam',
        player__online_id=uid,
    )

    for replay in replays:
        # Which team was the player on?
        player = replay.player_set.get(
            platform='OnlinePlatform_Steam',
            online_id=uid,
        )

        # What was the total score for this team?
        team_score = Player.objects.filter(
            replay=replay,
            team=player.team,
        ).exclude(
            pk=player.pk,
        ).aggregate(
            score=Sum('score'),
        )['score']

        if player.score > team_score:
            data['carries'] += 1

        # What was the total score for the other team?
        other_team_score = Player.objects.filter(
            replay=replay,
        ).exclude(
            team=player.team,
        ).aggregate(
            score=Sum('score'),
        )['score']

        if player.score > team_score + other_team_score:
            data['dominations'] += 1

    # The biggest gap in a win involving the player.
    data['biggest_win'] = None

    replays = Replay.objects.filter(
        team_sizes__gte=2,
        show_leaderboard=True,
        player__platform='OnlinePlatform_Steam',
        player__online_id=uid,
    ).extra(select={
        'goal_diff': 'abs("team_0_score" - "team_1_score")'
    }).order_by('-goal_diff')

    for replay in replays:
        # What team was this player on?
        player = replay.player_set.get(
            platform='OnlinePlatform_Steam',
            online_id=uid,
        )

        # Check if the player was on the winning team.
        if (
            player.team == 0 and replay.team_0_score > replay.team_1_score or
            player.team == 1 and replay.team_1_score > replay.team_0_score
        ):
            data['biggest_win'] = mark_safe('<a href="{}">{} - {}</a>'.format(
                replay.get_absolute_url(),
                replay.team_0_score,
                replay.team_1_score,
            ))
            break

    data.update(Player.objects.filter(
        platform='OnlinePlatform_Steam',
        online_id=uid,
    ).aggregate(
        highest_score=Max('score'),
        most_goals=Max('goals'),
        most_shots=Max('shots'),
        most_assists=Max('assists'),
        most_saves=Max('saves'),
    ))

    return data
