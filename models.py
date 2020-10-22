from otree.api import (
    models, widgets, BaseConstants, BaseSubsession, BaseGroup, BasePlayer,
    Currency as c, currency_range
)
import random
from collections import Counter
from django.db import models as djmodels
from django.db.models import Sum, Max, Count, Q
from itertools import cycle
import copy

import yaml

author = 'Evan DeFilippis'

doc = """
Word game involving interdependence and cooperation
"""


class Constants(BaseConstants):
    # Set the number of players in this game
    players_per_group = 2

    # Load yaml file containing scrabble values
    with open(r'./data/scrabble.yaml') as file:
        scrabble_data = yaml.load(file, Loader=yaml.FullLoader)

    # Define the points scored per letter (Scrabble values)
    letter_values = {k: v['value'] for k, v in scrabble_data.items()}
    scrabble_bag = [k for k, v in scrabble_data.items() for _ in range(v['quantity'])]

    # Import word list to validate words
    dictionary = open("data/wordlist.txt").read().splitlines()

    # URL name
    name_in_url = 'word-game'
    tile_size = 6

    # Number of rounds
    num_rounds = 37  # 5 + 16 + 16
    NON_EXISTENCE_VALUE = -1


class Subsession(BaseSubsession):
    def creating_session(self):
        # Generates tiles for the group on the first round
        for g in self.get_groups():
            g.regenerate_tiles()


class TileOwnerMixin:
    def get_tile_values(self, tile_list):
        return [Constants.letter_values[l] for l in tile_list]

    def get_available_tiles(self):
        return self.tiles.filter(used=False)

    def get_list_of_available_tiles(self):
        return list(self.get_available_tiles().values_list('letter', flat=True))

    def get_tile_colors(self):
        return list(self.get_available_tiles().values_list('color', flat=True))


class Group(TileOwnerMixin, BaseGroup):
    early_leave_vote = models.BooleanField(blank=True, null=True)
    early_leave_confirm = models.BooleanField(blank=True, null=True)

    @property
    def history(self):
        """
        return list of already submitted words by both group members
        """
        return list(self.words.values_list('_body', flat=True))

    # Scoring method if you want to get the score across all words submitted
    def total_score(self):
        group_score = self.words.aggregate(totwords=Sum('value'))['totwords']
        if group_score is None:
            return 0
        else:
            return group_score

    # Scoring method which takes maximum-valued word minus 1 point for all the incorrect submissions
    def current_score(self):
        aggs = self.words.aggregate(max_score=Max('value'), wrong_words=Count('value', filter=Q(value=-1)))
        max_score = aggs.get('max_score', 0)  # Max score for a given round
        wrong_words = aggs.get('wrong_words', 0)  # Total number of wrong words ever submitted

        if max_score is None:
            max_score = 0

        if wrong_words is None:
            wrong_words = 0

        if max_score == -1:
            return -1

        else:
            return max_score + (-1 * wrong_words)

    # Track the total amount of points scored through all the rounds
    def cumulative_score(self):
        return sum([i.current_score() for i in self.in_all_rounds()])

    @property
    def words(self):
        return Word.objects.filter(owner__group=self).order_by('-id')

    def regenerate_tiles(self):
        """Theoretically can be a transactional conflict here...."""
        self.get_available_tiles().update(used=True)
        tiles_to_add = []
        for p in self.get_players():
            tile_items = random.sample(Constants.scrabble_bag, k=Constants.tile_size)
            tiles = [Tile(owner=p, letter=i, group=self, color=random.choice(['R', 'B', 'G'])) for i in tile_items]
            tiles_to_add.extend(tiles)
        Tile.objects.bulk_create(tiles_to_add)

    def live_word(self, id_in_group, data):
        end_round = data.get('end_round')
        p = self.get_player_by_id(id_in_group)  # get player who submitted the word
        if end_round:
            if not self.early_leave_vote:
                p.voted_to_leave_early = True
                self.early_leave_vote = True

                return {0: dict(message_type='early_leave_vote', who_voted=id_in_group)}
            else:
                if p.voted_to_leave_early:  # chances are slim that they could vote twice because we
                    # disable voting button but if they do we still  block them here
                    return
                self.early_leave_vote = True  # do we need it? just to be sure is_displayed condition will be false...
                self.early_leave_confirm = True
                return {0: dict(message_type='early_leave_confirm')}
        w = data.get('word', '').upper()  # convert word to upper case
        if w:

            if w in self.history:
                error_resp = dict(id_in_group=id_in_group,
                                  error=True,
                                  message="You've already submitted this word"
                                  )
                return {id_in_group: error_resp}

            word = p.words.create()  # create new instance of "word model" in the database
            word.body = w  # set body method of word model to the word submitted
            current_score = self.current_score(),
            cumulative_score = self.cumulative_score()

            response = dict(id_in_group=id_in_group,
                            word=word.body,
                            word_value=word.value,
                            message=word.status,
                            current_score=current_score,
                            cumulative_score=cumulative_score,
                            rechistory=self.history
                            )

            # Create a new set of tiles
            TileSet.objects.create(word=word, tset=''.join(self.get_list_of_available_tiles()))

            # Un-comment this to regenerate tiles after every submission
            # self.regenerate_tiles()
            # response['group_tiles'] = self.get_list_of_available_tiles()
            # response['tile_colors'] = self.get_tile_colors()

            # Uncomment if tiles should only be re-generated upon success
            # if word.status == 'Success':
            #     TileSet.objects.create(word=word, tset=''.join(self.get_list_of_available_tiles()))
            #     self.regenerate_tiles()
            #     response['group_tiles'] = self.get_list_of_available_tiles()
            # else:
            #     self.regenerate_tiles()
            #     TileSet.objects.create(word=word, tset=''.join(self.get_list_of_available_tiles()))

            # returns a dictionary where the key is player id and the value is a dictionary of a users available tiles
            # and the response from the server to the submitted word
            resp_dict = {}
            for i in self.get_players():
                resp_dict[i.id_in_group] = {**response, 'own_tiles': "".join(i.get_list_of_available_tiles())}
            return resp_dict


class Player(TileOwnerMixin, BasePlayer):
    voted_to_leave_early = models.BooleanField()  # needed to track who exactly voted to leave early first

    @property
    def other(self):
        return self.get_others_in_group()[0]


class Word(djmodels.Model):
    owner = djmodels.ForeignKey(to=Player, related_name='words', on_delete=djmodels.CASCADE)
    _body = models.StringField()
    exists = models.BooleanField()
    attainable = models.BooleanField()
    value = models.IntegerField()

    def set_value(self, body):
        if self.exists and self.attainable:
            return sum([Constants.letter_values[l] for l in body])
        else:
            return Constants.NON_EXISTENCE_VALUE

    @property
    def body(self):
        return self._body

    def validate_word_r2(self, p1, p2):
        print("We are currently in Round 2")
        w = self.body
        c1 = cycle([p1, p2])
        c2 = cycle([p2, p1])
        return all(ch in next(c1) for ch in w) or all(ch in next(c2) for ch in w)

    def validate_word_r3(self, p1, p2, p1_colors, p2_colors):
        submitted_word = self.body

        # Zip P1 and P2's tiles together
        p1_zipped = list(zip(p1, p1_colors))
        p2_zipped = list(zip(p2, p2_colors))

        # Zip P1 and P2's tiles together
        list_of_tuples = p1_zipped + p2_zipped

        # Check length of word
        if len(submitted_word) == 0:
            return False

        # Initialise options for first character
        options = [[tup for tup in list_of_tuples if tup[0] == submitted_word[0]]]
        # Iterate through the rest of the characters
        for char in submitted_word[1:]:
            # Initialise set of characters in second position of previous tuple
            forbidden_chars = set(tup[1] for tup in options[-1])
            # Add valid options for the next character
            options.append([
                tup
                for tup in list_of_tuples
                if (tup[0] == char) and len(forbidden_chars - set(tup[1])) > 0
            ])
            # If there are no options, then submitted_word does not validate
            if len(options[-1]) == 0:
                return False
        return True

    def counterSubset(self, list1, list2):
        c1, c2 = Counter(list1), Counter(list2)
        for k, n in c1.items():
            if n > c2[k]:
                return False
        return True


    def is_attainable(self):
        current_round = self.owner.round_number

        # Phase 1 of the game
        if current_round >= 1 & current_round < 6:
            print("WHY IS THIS PRINTING OUTSIDE OF ROUND 6")
            return self.counterSubset(self.body, self.owner.group.get_list_of_available_tiles())

            #Un-comment if you don't need repeat letters to spell a word
            #return set(self.body).issubset(set(self.owner.group.get_list_of_available_tiles()))

        # Phase 2 of the game
        elif current_round >= 6 & current_round < 22:
            print("We are currently in Round 22")

            p1 = self.owner.get_list_of_available_tiles()
            p2 = self.owner.other.get_list_of_available_tiles()
            return self.validate_word_r2(p1, p2)

        # Phase 3 of the game
        else:
            p1 = self.owner.get_list_of_available_tiles()
            p2 = self.owner.other.get_list_of_available_tiles()
            p1_colors = self.owner.get_tile_colors()
            p2_colors = self.owner.other.get_tile_colors()

            return self.validate_word_r3(p1, p2, p1_colors, p2_colors)

    @body.setter
    def body(self, value):
        self._body = value
        self.exists = value in Constants.dictionary
        self.attainable = self.is_attainable()
        self.value = self.set_value(value)
        self.save()

    @property
    def status(self):
        print("The current round is:", self.owner.round_number)

        if self.exists and self.attainable:
            return 'Success'

        if not self.exists:
            return 'This word is not in the dictionary'

        if self.owner.round_number >= 1 & self.owner.round_number < 6:
            if self.exists and not self.attainable:
                return "You do not have the right tiles for this word"

        if self.owner.round_number >= 6 & self.owner.round_number < 22:
            if self.exists and not self.attainable:
                return "You can't construct this word by alterating tiles across player's hands"

        if self.owner.round_number >= 22:
            if self.exists and not self.attainable:
                return "This word requires using consecutive tiles of the same color"

        return "This word is not valid"


class Tile(djmodels.Model):
    # Tiles have an "owner" that is part of the Player class
    owner = djmodels.ForeignKey(to=Player, related_name='tiles', on_delete=djmodels.CASCADE)

    # Tiles have a "group" that is part of the Group class
    group = djmodels.ForeignKey(to=Group, related_name='tiles', on_delete=djmodels.CASCADE)
    letter = djmodels.CharField(max_length=1)

    # Tracks whether a tile is used
    used = models.BooleanField(initial=False)

    # Gives a color to every tile; only matters in round 3
    color = models.CharField(max_length=1, initial="R")


class TileSet(djmodels.Model):
    tset = models.StringField()
    word = djmodels.OneToOneField(to=Word, on_delete=djmodels.CASCADE)
    when = djmodels.DateTimeField(auto_now=True)


def custom_export(players):
    # header row
    yield ['session', 'participant_code', 'round_number', 'word', 'tiles', 'when', 'value']
    for t in TileSet.objects.all():
        yield [t.word.owner.session.code, t.word.owner.participant.code, t.word.owner.round_number,
               t.word.body, t.tset, str(t.when), t.word.value]
