"""NexusCore — Economy: currency, bank, daily, work, crime, shop, gambling, leaderboards, pets, heists."""

from __future__ import annotations

import asyncio
import datetime
import random
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    duration_str, safe_send, safe_dm, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
ECO_DEFAULTS_GUILD = {
    "enabled": True,
    "currency_name": "coins",
    "currency_emoji": "🪙",
    "currency_symbol": "$",
    "starting_balance": 100,
    "max_balance": 10000000,
    "log_channel": None,
    "daily_amount": 200,
    "daily_streak_bonus": 50,
    "weekly_amount": 1500,
    "work_min": 50,
    "work_max": 300,
    "work_cooldown": 3600,
    "work_messages": [
        "You worked as a programmer and earned {amount}!",
        "You delivered packages and earned {amount}!",
        "You fixed a car and earned {amount}!",
        "You tutored students and earned {amount}!",
        "You walked dogs and earned {amount}!",
        "You painted a house and earned {amount}!",
        "You drove a taxi and earned {amount}!",
        "You cooked meals and earned {amount}!",
    ],
    "crime_min": 100,
    "crime_max": 800,
    "crime_cooldown": 7200,
    "crime_fail_chance": 40,
    "crime_fine_min": 50,
    "crime_fine_max": 400,
    "crime_messages": [
        "You robbed a bank and got {amount}!",
        "You hacked into a mainframe and stole {amount}!",
        "You ran a scam and pocketed {amount}!",
        "You sold counterfeit goods for {amount}!",
    ],
    "crime_fail_messages": [
        "You got caught and fined {fine}!",
        "The police caught you! You lost {fine}.",
        "Your heist failed! You paid {fine} in fines.",
    ],
    "rob_enabled": True,
    "rob_cooldown": 14400,
    "rob_success_chance": 45,
    "rob_min_percent": 5,
    "rob_max_percent": 30,
    "rob_min_target_balance": 500,
    "interest_rate": 0.5,
    "interest_interval": 86400,
    "tax_rate": 0,
    "shop_items": {},
    # item_id -> {name, description, price, emoji, role_id, stock, max_per_user, usable, on_use_msg, type: "role"|"item"|"consumable"}
    "gambling": {
        "coinflip_enabled": True,
        "slots_enabled": True,
        "blackjack_enabled": True,
        "roulette_enabled": True,
        "dice_enabled": True,
        "max_bet": 50000,
        "min_bet": 10,
        "slots_jackpot_multi": 10,
        "slots_three_multi": 5,
        "slots_two_multi": 2,
        "blackjack_multi": 2,
    },
    "pets": {
        "enabled": True,
        "types": {
            "cat": {"emoji": "🐱", "base_price": 500, "daily_earn": 20},
            "dog": {"emoji": "🐶", "base_price": 500, "daily_earn": 20},
            "bird": {"emoji": "🐦", "base_price": 300, "daily_earn": 15},
            "fish": {"emoji": "🐟", "base_price": 200, "daily_earn": 10},
            "dragon": {"emoji": "🐉", "base_price": 5000, "daily_earn": 100},
            "unicorn": {"emoji": "🦄", "base_price": 10000, "daily_earn": 200},
        },
    },
    "heist": {
        "enabled": True,
        "min_players": 2,
        "max_players": 10,
        "join_time": 60,
        "min_bet": 100,
        "base_success": 50,
        "per_player_bonus": 5,
        "payout_multi": 3,
        "cooldown": 3600,
    },
}

ECO_DEFAULTS_MEMBER = {
    "wallet": 0,
    "bank": 0,
    "bank_limit": 10000,
    "total_earned": 0,
    "total_spent": 0,
    "daily_streak": 0,
    "last_daily": 0,
    "last_weekly": 0,
    "last_work": 0,
    "last_crime": 0,
    "last_rob": 0,
    "last_heist": 0,
    "inventory": {},    # item_id -> count
    "pets": {},         # pet_name -> {type, level, xp, fed_at, happiness}
    "transactions": [], # last 50 transactions
}

# ── Slot emojis ────────────────────────────────────────────────────────────
SLOT_EMOJIS = ["🍒", "🍋", "🍊", "🍇", "🍉", "⭐", "💎", "7️⃣"]


# ── Views ──────────────────────────────────────────────────────────────────
class HeistJoinView(discord.ui.View):
    def __init__(self, cog, leader: discord.Member, bet: int):
        super().__init__(timeout=70)
        self.cog = cog
        self.leader = leader
        self.bet = bet
        self.participants = {leader.id}

    @discord.ui.button(label="🔫 Join Heist", style=discord.ButtonStyle.danger)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.participants:
            return await interaction.response.send_message("Already in!", ephemeral=True)

        bal = await self.cog.eco_config.member(interaction.user).wallet()
        if bal < self.bet:
            return await interaction.response.send_message(f"You need {self.bet} in your wallet.", ephemeral=True)

        heist_data = await self.cog.eco_config.guild(interaction.guild).heist()
        if len(self.participants) >= heist_data.get("max_players", 10):
            return await interaction.response.send_message("Heist is full!", ephemeral=True)

        self.participants.add(interaction.user.id)
        await interaction.response.send_message(
            f"🔫 {interaction.user.display_name} joined! ({len(self.participants)} members)",
        )

    @discord.ui.button(label="Participants: 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def count_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass


class BlackjackView(discord.ui.View):
    def __init__(self, cog, player: discord.Member, bet: int, player_hand: list, dealer_hand: list, deck: list):
        super().__init__(timeout=60)
        self.cog = cog
        self.player = player
        self.bet = bet
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.deck = deck
        self.stood = False

    def _hand_value(self, hand):
        value = 0
        aces = 0
        for card in hand:
            if card[0] in ("J", "Q", "K"):
                value += 10
            elif card[0] == "A":
                aces += 1
                value += 11
            else:
                value += int(card[0])
        while value > 21 and aces:
            value -= 10
            aces -= 1
        return value

    def _hand_str(self, hand, hide_second=False):
        suits = {"H": "♥️", "D": "♦️", "C": "♣️", "S": "♠️"}
        if hide_second and len(hand) > 1:
            return f"`{hand[0][0]}{suits.get(hand[0][1], '?')}` `??`"
        return " ".join(f"`{c[0]}{suits.get(c[1], '?')}`" for c in hand)

    def _build_embed(self, reveal=False):
        pv = self._hand_value(self.player_hand)
        embed = discord.Embed(title="🃏 Blackjack", colour=Clr.ECO)
        embed.add_field(
            name=f"Dealer {f'({self._hand_value(self.dealer_hand)})' if reveal else ''}",
            value=self._hand_str(self.dealer_hand, hide_second=not reveal),
            inline=False,
        )
        embed.add_field(
            name=f"You ({pv})",
            value=self._hand_str(self.player_hand),
            inline=False,
        )
        embed.set_footer(text=f"Bet: {self.bet}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Not your game.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player_hand.append(self.deck.pop())
        pv = self._hand_value(self.player_hand)
        if pv > 21:
            embed = self._build_embed(reveal=True)
            embed.description = f"💥 Bust! You lost **{self.bet}**."
            embed.colour = Clr.ERROR
            await self.cog._add_transaction(interaction.user, -self.bet, "Blackjack loss")
            self.stop()
            await interaction.response.edit_message(embed=embed, view=None)
        elif pv == 21:
            await self._resolve(interaction)
        else:
            await interaction.response.edit_message(embed=self._build_embed())

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction)

    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.danger, emoji="💰")
    async def double_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = await self.cog.eco_config.member(interaction.user).wallet()
        if bal < self.bet:
            return await interaction.response.send_message("Not enough to double.", ephemeral=True)
        self.bet *= 2
        self.player_hand.append(self.deck.pop())
        await self._resolve(interaction)

    async def _resolve(self, interaction: discord.Interaction):
        self.stop()
        # Dealer draws
        while self._hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())

        pv = self._hand_value(self.player_hand)
        dv = self._hand_value(self.dealer_hand)
        embed = self._build_embed(reveal=True)

        if pv > 21:
            result = "lose"
        elif dv > 21:
            result = "win"
        elif pv > dv:
            result = "win"
        elif pv < dv:
            result = "lose"
        else:
            result = "tie"

        settings = await self.cog.eco_config.guild(interaction.guild).gambling()
        multi = settings.get("blackjack_multi", 2)

        if result == "win":
            winnings = int(self.bet * multi)
            embed.description = f"🎉 You won **{winnings}**!"
            embed.colour = Clr.SUCCESS
            await self.cog._add_balance(interaction.user, winnings)
            await self.cog._add_transaction(interaction.user, winnings, "Blackjack win")
        elif result == "lose":
            embed.description = f"💔 You lost **{self.bet}**."
            embed.colour = Clr.ERROR
            await self.cog._add_transaction(interaction.user, -self.bet, "Blackjack loss")
        else:
            embed.description = f"🤝 Push! Bet returned."
            embed.colour = Clr.INFO
            await self.cog._add_balance(interaction.user, self.bet)

        await interaction.response.edit_message(embed=embed, view=None)


class ShopView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild, items: dict):
        super().__init__(timeout=120)
        self.cog = cog
        options = []
        for item_id, item in list(items.items())[:25]:
            if item.get("stock", -1) == 0:
                continue
            options.append(discord.SelectOption(
                label=item["name"],
                value=item_id,
                description=f"{item['price']} {item.get('emoji', '🪙')} — {(item.get('description', '') or '')[:80]}",
                emoji=item.get("emoji"),
            ))
        if options:
            self.sel = discord.ui.Select(placeholder="Buy an item...", options=options)
            self.sel.callback = self.on_select
            self.add_item(self.sel)
        self.guild = guild

    async def on_select(self, interaction: discord.Interaction):
        item_id = self.sel.values[0]
        await self.cog._buy_item(interaction, item_id)


# ── Mixin ──────────────────────────────────────────────────────────────────
class EconomyMixin:
    """Economy system mixin."""

    def _init_economy(self, bot):
        self.eco_config = Config.get_conf(
            None, identifier=900008, cog_name="NexusCoreEco"
        )
        self.eco_config.register_guild(**ECO_DEFAULTS_GUILD)
        self.eco_config.register_member(**ECO_DEFAULTS_MEMBER)
        self.bot = bot

    # ── Balance helpers ────────────────────────────────────────────────────
    async def _get_balance(self, member: discord.Member) -> tuple[int, int]:
        data = await self.eco_config.member(member).all()
        return data["wallet"], data["bank"]

    async def _add_balance(self, member: discord.Member, amount: int, to: str = "wallet"):
        if to == "wallet":
            current = await self.eco_config.member(member).wallet()
            await self.eco_config.member(member).wallet.set(current + amount)
        else:
            current = await self.eco_config.member(member).bank()
            await self.eco_config.member(member).bank.set(current + amount)
        if amount > 0:
            earned = await self.eco_config.member(member).total_earned()
            await self.eco_config.member(member).total_earned.set(earned + amount)

    async def _remove_balance(self, member: discord.Member, amount: int, from_: str = "wallet") -> bool:
        if from_ == "wallet":
            current = await self.eco_config.member(member).wallet()
        else:
            current = await self.eco_config.member(member).bank()
        if current < amount:
            return False
        if from_ == "wallet":
            await self.eco_config.member(member).wallet.set(current - amount)
        else:
            await self.eco_config.member(member).bank.set(current - amount)
        spent = await self.eco_config.member(member).total_spent()
        await self.eco_config.member(member).total_spent.set(spent + amount)
        return True

    async def _add_transaction(self, member: discord.Member, amount: int, description: str):
        async with self.eco_config.member(member).transactions() as txns:
            txns.append({"amount": amount, "desc": description, "at": ts_now()})
            if len(txns) > 50:
                txns.pop(0)

    async def _format_amount(self, guild: discord.Guild, amount: int) -> str:
        data = await self.eco_config.guild(guild).all()
        return f"{data['currency_emoji']} {amount:,} {data['currency_name']}"

    # ── Daily ──────────────────────────────────────────────────────────────
    async def _daily(self, ctx: commands.Context):
        member = ctx.author
        guild_data = await self.eco_config.guild(ctx.guild).all()
        member_data = await self.eco_config.member(member).all()

        now = ts_now()
        last = member_data["last_daily"]
        if now - last < 86400:
            remaining = 86400 - (now - last)
            return await ctx.send(embed=err_embed(f"Daily available {ts_relative(now + remaining)}"))

        streak = member_data["daily_streak"]
        # Check if within 48h for streak
        if last and now - last < 172800:
            streak += 1
        else:
            streak = 1

        amount = guild_data["daily_amount"] + (guild_data["daily_streak_bonus"] * (streak - 1))
        await self._add_balance(member, amount)
        await self.eco_config.member(member).last_daily.set(now)
        await self.eco_config.member(member).daily_streak.set(streak)
        await self._add_transaction(member, amount, "Daily reward")

        embed = discord.Embed(
            title="📅 Daily Reward",
            description=f"You received **{await self._format_amount(ctx.guild, amount)}**!",
            colour=Clr.ECO,
        )
        if streak > 1:
            embed.add_field(name="🔥 Streak", value=f"{streak} days (+{guild_data['daily_streak_bonus'] * (streak - 1)} bonus)")
        await ctx.send(embed=embed)

    # ── Weekly ─────────────────────────────────────────────────────────────
    async def _weekly(self, ctx: commands.Context):
        member = ctx.author
        guild_data = await self.eco_config.guild(ctx.guild).all()
        last = await self.eco_config.member(member).last_weekly()
        now = ts_now()
        if now - last < 604800:
            remaining = 604800 - (now - last)
            return await ctx.send(embed=err_embed(f"Weekly available {ts_relative(now + remaining)}"))

        amount = guild_data["weekly_amount"]
        await self._add_balance(member, amount)
        await self.eco_config.member(member).last_weekly.set(now)
        await self._add_transaction(member, amount, "Weekly reward")
        await ctx.send(embed=ok_embed(f"You received **{await self._format_amount(ctx.guild, amount)}**!"))

    # ── Work ───────────────────────────────────────────────────────────────
    async def _work(self, ctx: commands.Context):
        guild_data = await self.eco_config.guild(ctx.guild).all()
        last = await self.eco_config.member(ctx.author).last_work()
        now = ts_now()
        cd = guild_data["work_cooldown"]
        if now - last < cd:
            return await ctx.send(embed=err_embed(f"Work available {ts_relative(now + cd - (now - last))}"))

        amount = random.randint(guild_data["work_min"], guild_data["work_max"])
        msg = random.choice(guild_data["work_messages"]).format(
            amount=await self._format_amount(ctx.guild, amount)
        )
        await self._add_balance(ctx.author, amount)
        await self.eco_config.member(ctx.author).last_work.set(now)
        await self._add_transaction(ctx.author, amount, "Work")
        await ctx.send(embed=discord.Embed(description=f"💼 {msg}", colour=Clr.ECO))

    # ── Crime ──────────────────────────────────────────────────────────────
    async def _crime(self, ctx: commands.Context):
        guild_data = await self.eco_config.guild(ctx.guild).all()
        last = await self.eco_config.member(ctx.author).last_crime()
        now = ts_now()
        cd = guild_data["crime_cooldown"]
        if now - last < cd:
            return await ctx.send(embed=err_embed(f"Crime available {ts_relative(now + cd - (now - last))}"))

        await self.eco_config.member(ctx.author).last_crime.set(now)

        if random.randint(1, 100) <= guild_data["crime_fail_chance"]:
            fine = random.randint(guild_data["crime_fine_min"], guild_data["crime_fine_max"])
            await self._remove_balance(ctx.author, min(fine, (await self.eco_config.member(ctx.author).wallet())))
            msg = random.choice(guild_data["crime_fail_messages"]).format(
                fine=await self._format_amount(ctx.guild, fine)
            )
            await self._add_transaction(ctx.author, -fine, "Crime (failed)")
            await ctx.send(embed=discord.Embed(description=f"🚔 {msg}", colour=Clr.ERROR))
        else:
            amount = random.randint(guild_data["crime_min"], guild_data["crime_max"])
            msg = random.choice(guild_data["crime_messages"]).format(
                amount=await self._format_amount(ctx.guild, amount)
            )
            await self._add_balance(ctx.author, amount)
            await self._add_transaction(ctx.author, amount, "Crime")
            await ctx.send(embed=discord.Embed(description=f"🦹 {msg}", colour=Clr.ECO))

    # ── Rob ────────────────────────────────────────────────────────────────
    async def _rob(self, ctx: commands.Context, target: discord.Member):
        guild_data = await self.eco_config.guild(ctx.guild).all()
        if not guild_data["rob_enabled"]:
            return await ctx.send(embed=err_embed("Robbing is disabled."))
        if target.id == ctx.author.id:
            return await ctx.send(embed=err_embed("You can't rob yourself."))
        if target.bot:
            return await ctx.send(embed=err_embed("You can't rob bots."))

        last = await self.eco_config.member(ctx.author).last_rob()
        now = ts_now()
        cd = guild_data["rob_cooldown"]
        if now - last < cd:
            return await ctx.send(embed=err_embed(f"Rob available {ts_relative(now + cd - (now - last))}"))

        target_wallet = await self.eco_config.member(target).wallet()
        if target_wallet < guild_data["rob_min_target_balance"]:
            return await ctx.send(embed=err_embed(f"Target needs at least {guild_data['rob_min_target_balance']} in wallet."))

        await self.eco_config.member(ctx.author).last_rob.set(now)

        if random.randint(1, 100) <= guild_data["rob_success_chance"]:
            percent = random.randint(guild_data["rob_min_percent"], guild_data["rob_max_percent"])
            stolen = int(target_wallet * percent / 100)
            stolen = max(1, stolen)
            await self._remove_balance(target, stolen)
            await self._add_balance(ctx.author, stolen)
            await self._add_transaction(ctx.author, stolen, f"Robbed {target}")
            await self._add_transaction(target, -stolen, f"Robbed by {ctx.author}")
            await ctx.send(embed=discord.Embed(
                description=f"🔫 You robbed **{await self._format_amount(ctx.guild, stolen)}** from {target.mention}!",
                colour=Clr.ECO,
            ))
        else:
            fine = random.randint(50, 200)
            wallet = await self.eco_config.member(ctx.author).wallet()
            fine = min(fine, wallet)
            await self._remove_balance(ctx.author, fine)
            await self._add_transaction(ctx.author, -fine, f"Failed rob on {target}")
            await ctx.send(embed=discord.Embed(
                description=f"🚔 You failed to rob {target.mention} and lost **{await self._format_amount(ctx.guild, fine)}**!",
                colour=Clr.ERROR,
            ))

    # ── Deposit / Withdraw ─────────────────────────────────────────────────
    async def _deposit(self, ctx: commands.Context, amount: int):
        wallet = await self.eco_config.member(ctx.author).wallet()
        bank = await self.eco_config.member(ctx.author).bank()
        bank_limit = await self.eco_config.member(ctx.author).bank_limit()
        if amount > wallet:
            return await ctx.send(embed=err_embed("Not enough in wallet."))
        if bank + amount > bank_limit:
            return await ctx.send(embed=err_embed(f"Bank limit is {bank_limit:,}. You can deposit {bank_limit - bank:,}."))
        await self._remove_balance(ctx.author, amount, "wallet")
        await self._add_balance(ctx.author, amount, "bank")
        await ctx.send(embed=ok_embed(f"Deposited **{await self._format_amount(ctx.guild, amount)}** to bank."))

    async def _withdraw(self, ctx: commands.Context, amount: int):
        bank = await self.eco_config.member(ctx.author).bank()
        if amount > bank:
            return await ctx.send(embed=err_embed("Not enough in bank."))
        await self._remove_balance(ctx.author, amount, "bank")
        await self._add_balance(ctx.author, amount, "wallet")
        await ctx.send(embed=ok_embed(f"Withdrew **{await self._format_amount(ctx.guild, amount)}** to wallet."))

    # ── Gambling: Coinflip ─────────────────────────────────────────────────
    async def _coinflip(self, ctx: commands.Context, bet: int, choice: str):
        settings = await self.eco_config.guild(ctx.guild).gambling()
        if not settings.get("coinflip_enabled"):
            return await ctx.send(embed=err_embed("Coinflip is disabled."))
        if bet < settings["min_bet"] or bet > settings["max_bet"]:
            return await ctx.send(embed=err_embed(f"Bet must be {settings['min_bet']:,}–{settings['max_bet']:,}."))

        wallet = await self.eco_config.member(ctx.author).wallet()
        if bet > wallet:
            return await ctx.send(embed=err_embed("Not enough coins."))

        await self._remove_balance(ctx.author, bet)
        result = random.choice(["heads", "tails"])
        won = choice.lower() in (result, result[0])

        if won:
            winnings = bet * 2
            await self._add_balance(ctx.author, winnings)
            await self._add_transaction(ctx.author, bet, "Coinflip win")
            embed = discord.Embed(
                title=f"🪙 {result.title()}!",
                description=f"You won **{await self._format_amount(ctx.guild, winnings)}**!",
                colour=Clr.SUCCESS,
            )
        else:
            await self._add_transaction(ctx.author, -bet, "Coinflip loss")
            embed = discord.Embed(
                title=f"🪙 {result.title()}!",
                description=f"You lost **{await self._format_amount(ctx.guild, bet)}**.",
                colour=Clr.ERROR,
            )
        await ctx.send(embed=embed)

    # ── Gambling: Slots ────────────────────────────────────────────────────
    async def _slots(self, ctx: commands.Context, bet: int):
        settings = await self.eco_config.guild(ctx.guild).gambling()
        if not settings.get("slots_enabled"):
            return await ctx.send(embed=err_embed("Slots are disabled."))
        if bet < settings["min_bet"] or bet > settings["max_bet"]:
            return await ctx.send(embed=err_embed(f"Bet must be {settings['min_bet']:,}–{settings['max_bet']:,}."))

        wallet = await self.eco_config.member(ctx.author).wallet()
        if bet > wallet:
            return await ctx.send(embed=err_embed("Not enough coins."))

        await self._remove_balance(ctx.author, bet)
        reels = [random.choice(SLOT_EMOJIS) for _ in range(3)]

        if reels[0] == reels[1] == reels[2]:
            if reels[0] == "💎":
                multi = settings["slots_jackpot_multi"]
                title = "💎 JACKPOT! 💎"
            else:
                multi = settings["slots_three_multi"]
                title = "🎰 Three of a kind!"
            winnings = bet * multi
            colour = Clr.SUCCESS
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            multi = settings["slots_two_multi"]
            winnings = bet * multi
            title = "🎰 Two matching!"
            colour = Clr.ECO
        else:
            winnings = 0
            title = "🎰 No match"
            colour = Clr.ERROR

        if winnings:
            await self._add_balance(ctx.author, winnings)
            await self._add_transaction(ctx.author, winnings - bet, "Slots")
            desc = f"**[ {' | '.join(reels)} ]**\n\nYou won **{await self._format_amount(ctx.guild, winnings)}**!"
        else:
            await self._add_transaction(ctx.author, -bet, "Slots loss")
            desc = f"**[ {' | '.join(reels)} ]**\n\nYou lost **{await self._format_amount(ctx.guild, bet)}**."

        await ctx.send(embed=discord.Embed(title=title, description=desc, colour=colour))

    # ── Gambling: Blackjack ────────────────────────────────────────────────
    async def _blackjack(self, ctx: commands.Context, bet: int):
        settings = await self.eco_config.guild(ctx.guild).gambling()
        if not settings.get("blackjack_enabled"):
            return await ctx.send(embed=err_embed("Blackjack is disabled."))
        if bet < settings["min_bet"] or bet > settings["max_bet"]:
            return await ctx.send(embed=err_embed(f"Bet must be {settings['min_bet']:,}–{settings['max_bet']:,}."))

        wallet = await self.eco_config.member(ctx.author).wallet()
        if bet > wallet:
            return await ctx.send(embed=err_embed("Not enough coins."))

        await self._remove_balance(ctx.author, bet)

        ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
        suits = ["H", "D", "C", "S"]
        deck = [(r, s) for r in ranks for s in suits]
        random.shuffle(deck)

        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        view = BlackjackView(self, ctx.author, bet, player_hand, dealer_hand, deck)
        embed = view._build_embed()
        await ctx.send(embed=embed, view=view)

    # ── Shop ───────────────────────────────────────────────────────────────
    async def _buy_item(self, interaction: discord.Interaction, item_id: str):
        guild_data = await self.eco_config.guild(interaction.guild).all()
        item = guild_data["shop_items"].get(item_id)
        if not item:
            return await interaction.response.send_message("Item not found.", ephemeral=True)

        wallet = await self.eco_config.member(interaction.user).wallet()
        if wallet < item["price"]:
            return await interaction.response.send_message("Not enough coins!", ephemeral=True)

        member_data = await self.eco_config.member(interaction.user).all()
        inv = member_data.get("inventory", {})
        current_count = inv.get(item_id, 0)
        if item.get("max_per_user") and current_count >= item["max_per_user"]:
            return await interaction.response.send_message("You have the max amount of this item.", ephemeral=True)

        if item.get("stock", -1) == 0:
            return await interaction.response.send_message("Out of stock!", ephemeral=True)

        await self._remove_balance(interaction.user, item["price"])
        async with self.eco_config.member(interaction.user).inventory() as inv:
            inv[item_id] = inv.get(item_id, 0) + 1

        if item.get("stock", -1) > 0:
            async with self.eco_config.guild(interaction.guild).shop_items() as items:
                if item_id in items:
                    items[item_id]["stock"] -= 1

        if item.get("type") == "role" and item.get("role_id"):
            role = interaction.guild.get_role(item["role_id"])
            if role:
                try:
                    await interaction.user.add_roles(role, reason="NexusCore shop purchase")
                except discord.HTTPException:
                    pass

        await self._add_transaction(interaction.user, -item["price"], f"Bought {item['name']}")
        emoji = item.get("emoji", "🛒")
        await interaction.response.send_message(
            f"{emoji} Purchased **{item['name']}** for **{item['price']:,}**!", ephemeral=True
        )

    # ── Heist ──────────────────────────────────────────────────────────────
    async def _start_heist(self, ctx: commands.Context, bet: int):
        guild_data = await self.eco_config.guild(ctx.guild).all()
        heist = guild_data.get("heist", {})
        if not heist.get("enabled"):
            return await ctx.send(embed=err_embed("Heists are disabled."))

        last = await self.eco_config.member(ctx.author).last_heist()
        now = ts_now()
        cd = heist.get("cooldown", 3600)
        if now - last < cd:
            return await ctx.send(embed=err_embed(f"Heist available {ts_relative(now + cd - (now - last))}"))

        if bet < heist.get("min_bet", 100):
            return await ctx.send(embed=err_embed(f"Minimum bet: {heist['min_bet']:,}"))

        wallet = await self.eco_config.member(ctx.author).wallet()
        if wallet < bet:
            return await ctx.send(embed=err_embed("Not enough coins."))

        view = HeistJoinView(self, ctx.author, bet)
        embed = discord.Embed(
            title="🔫 HEIST — Recruiting!",
            description=f"**{ctx.author.display_name}** is planning a heist!\n\nBet: **{bet:,}** each\nClick below to join!\n\nStarting {ts_relative(now + heist.get('join_time', 60))}",
            colour=Clr.ECO,
        )
        msg = await ctx.send(embed=embed, view=view)
        await asyncio.sleep(heist.get("join_time", 60))

        participants = list(view.participants)
        if len(participants) < heist.get("min_players", 2):
            embed.description = "❌ Not enough players. Heist cancelled."
            embed.colour = Clr.ERROR
            return await msg.edit(embed=embed, view=None)

        # Deduct bets
        for uid in participants:
            member = ctx.guild.get_member(uid)
            if member:
                await self._remove_balance(member, bet)

        # Calculate success
        base = heist.get("base_success", 50)
        bonus = heist.get("per_player_bonus", 5)
        success_chance = min(90, base + bonus * len(participants))
        success = random.randint(1, 100) <= success_chance

        if success:
            payout = int(bet * heist.get("payout_multi", 3))
            for uid in participants:
                member = ctx.guild.get_member(uid)
                if member:
                    await self._add_balance(member, payout)
                    await self._add_transaction(member, payout - bet, "Heist success")
                    await self.eco_config.member(member).last_heist.set(now)
            mentions = ", ".join(f"<@{uid}>" for uid in participants)
            embed = discord.Embed(
                title="🔫 HEIST SUCCESS!",
                description=f"The crew pulled it off!\n\n{mentions}\n\nEach member earned **{payout:,}**!",
                colour=Clr.SUCCESS,
            )
        else:
            for uid in participants:
                member = ctx.guild.get_member(uid)
                if member:
                    await self._add_transaction(member, -bet, "Heist failed")
                    await self.eco_config.member(member).last_heist.set(now)
            embed = discord.Embed(
                title="🚔 HEIST FAILED!",
                description=f"The heist went wrong! Everyone lost their **{bet:,}** bet.",
                colour=Clr.ERROR,
            )

        await msg.edit(embed=embed, view=None)

    # ── Pets ───────────────────────────────────────────────────────────────
    async def _buy_pet(self, ctx: commands.Context, pet_type: str, name: str):
        guild_data = await self.eco_config.guild(ctx.guild).all()
        pets_conf = guild_data.get("pets", {})
        if not pets_conf.get("enabled"):
            return await ctx.send(embed=err_embed("Pets are disabled."))

        types = pets_conf.get("types", {})
        if pet_type not in types:
            available = ", ".join(f"{v['emoji']} {k}" for k, v in types.items())
            return await ctx.send(embed=err_embed(f"Unknown type. Available: {available}"))

        pet_info = types[pet_type]
        price = pet_info["base_price"]
        wallet = await self.eco_config.member(ctx.author).wallet()
        if wallet < price:
            return await ctx.send(embed=err_embed(f"You need {price:,} coins."))

        async with self.eco_config.member(ctx.author).pets() as pets:
            if name in pets:
                return await ctx.send(embed=err_embed(f"You already have a pet named `{name}`."))
            await self._remove_balance(ctx.author, price)
            pets[name] = {
                "type": pet_type,
                "level": 1,
                "xp": 0,
                "happiness": 100,
                "fed_at": ts_now(),
                "bought_at": ts_now(),
            }

        await self._add_transaction(ctx.author, -price, f"Bought pet: {name}")
        await ctx.send(embed=discord.Embed(
            title=f"{pet_info['emoji']} New Pet!",
            description=f"You adopted **{name}** the {pet_type}!",
            colour=Clr.ECO,
        ))

    async def _feed_pet(self, ctx: commands.Context, name: str):
        async with self.eco_config.member(ctx.author).pets() as pets:
            if name not in pets:
                return await ctx.send(embed=err_embed(f"No pet named `{name}`."))
            pet = pets[name]
            pet["fed_at"] = ts_now()
            pet["happiness"] = min(100, pet["happiness"] + 20)
            pet["xp"] += 10
            if pet["xp"] >= pet["level"] * 100:
                pet["xp"] = 0
                pet["level"] += 1
                await ctx.send(embed=ok_embed(f"**{name}** leveled up to **{pet['level']}**! 🎉"))
            pets[name] = pet

        await ctx.send(embed=ok_embed(f"Fed **{name}**! Happiness: {pet['happiness']}%"))

    async def _pet_collect(self, ctx: commands.Context):
        """Collect daily earnings from all pets."""
        guild_data = await self.eco_config.guild(ctx.guild).all()
        types = guild_data.get("pets", {}).get("types", {})
        pets = await self.eco_config.member(ctx.author).pets()
        if not pets:
            return await ctx.send(embed=err_embed("You have no pets."))

        total = 0
        for name, pet in pets.items():
            ptype = types.get(pet["type"], {})
            base_earn = ptype.get("daily_earn", 10)
            level_bonus = pet.get("level", 1) * 5
            happiness_multi = pet.get("happiness", 50) / 100
            earn = int((base_earn + level_bonus) * happiness_multi)
            total += earn

        if total > 0:
            await self._add_balance(ctx.author, total)
            await self._add_transaction(ctx.author, total, "Pet earnings")
            await ctx.send(embed=ok_embed(
                f"Your pets earned **{await self._format_amount(ctx.guild, total)}**! ({len(pets)} pets)"
            ))
        else:
            await ctx.send(embed=err_embed("Your pets didn't earn anything. Feed them!"))
