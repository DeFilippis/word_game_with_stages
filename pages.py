from otree.api import Currency as c, currency_range
from ._builtin import Page, WaitPage
from otree.live import _live_send_back

class MyWaitPage(WaitPage):
    def is_displayed(self):
        return self.round_number == 1

    group_by_arrival_time = True

class SecondWP(WaitPage):
    after_all_players_arrive = 'regenerate_tiles'


class Game_Page(Page):
    timeout_seconds = 240 + 45 #4 minutes and 45 seconds
    live_method = 'live_word'

    def before_next_page(self):
        if self.group.early_leave_vote and self.group.early_leave_confirm:
            group_codes = [(i.participant.code, i.id_in_group) for i in self.group.get_players()]
            retdict = {c: {'id_in_group': i, 'endgame': True} for c, i in group_codes}
            _live_send_back(self.session.code, self._index_in_pages, pcode_retval=retdict)

    def vars_for_template(self):
        own_tiles = self.player.get_list_of_available_tiles()
        own_tiles_value = [str(v) for v in self.player.get_tile_values(own_tiles)]
        own_tiles_colors = self.player.get_tile_colors()
        letter_color_tuple = [(letter, color) for letter, color in zip(own_tiles, own_tiles_colors)]

        return dict(
            tile_value_tuple=[(own_tiles[i], own_tiles_value[i]) for i in range(0, len(own_tiles_value))],
            own_tiles="".join(own_tiles),
            own_tiles_value="".join(own_tiles_value),
            group_tiles=''.join(self.group.get_list_of_available_tiles()),
            own_tiles_colors="".join(own_tiles_colors),
            letter_color_tuple=letter_color_tuple
        )

class Play_Game_R1(Game_Page):
    def is_displayed(self):
        # rounds 1 - 5 should be the "easy" game
        return self.round_number < 6 and not (self.group.early_leave_vote and self.group.early_leave_confirm)



class Play_Game_R2(Game_Page):
    def is_displayed(self):
        # rounds 6 - 21 should be the "medium" difficulty game (16 rounds)
        return self.round_number >= 6 and self.round_number < 22 and not (self.group.early_leave_vote and self.group.early_leave_confirm)



class Play_Game_R3(Game_Page):
    def is_displayed(self):
        # rounds 22 - 37 should be the "medium" difficulty game (16 rounds)
        return self.round_number >= 22


class MyWaitPage(WaitPage):
    group_by_arrival_time = True


page_sequence = [
    MyWaitPage,
    SecondWP,
    Play_Game_R1,
    Play_Game_R2,
    Play_Game_R3,
]
