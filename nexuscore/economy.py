"""NexusCore — Economy v2: wallet+bank, daily/weekly streaks, work/crime/rob, coinflip/slots/blackjack,
roulette, dice, lottery, stock market, fishing, mining, crafting, achievements, income roles, auction house,
shop, heist, pets (6 types), gambling stats, leaderboard."""

from __future__ import annotations

import asyncio
import datetime
import random
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    duration_str, parse_duration, safe_send, safe_dm, ConfirmView, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
ECO_DEFAULTS_GUILD = {
    "enabled": True,
    "currency_name": "Coins",
    "currency_emoji": "🪙",
    "currency_symbol": "$",
    "daily_amount": 100,
    "daily_streak_bonus": 10,
    "weekly_amount": 500,
    "weekly_streak_bonus": 50,
    "work_min": 50,
    "work_max": 200,
    "work_cooldown": 3600,
    "crime_min": 100,
    "crime_max": 500,
    "crime_cooldown": 7200,
    "crime_fail_chance": 40,
    "crime_fine_pct": 30,
    "rob_enabled": True,
    "rob_cooldown": 14400,
    "rob_min_wallet": 500,
    "rob_fail_chance": 50,
    "rob_max_pct": 50,
    "tax_rate": 0,
    "interest_rate": 2,
    "interest_cap": 100000,
    "max_bank": 0,          # 0 = unlimited
    "shop_items": {},
    "log_channel": None,
    "gambling_tax": 0,
    "min_bet": 10,
    "max_bet": 100000,
    "slots_emojis": ["🍎", "🍊", "🍇", "🍒", "🍋", "💎", "7️⃣"],
    "work_responses": [
        "You worked as a programmer and earned {amount}!",
        "You did some freelance work and earned {amount}!",
        "You delivered pizzas and earned {amount}!",
        "You mowed lawns and earned {amount}!",
        "You walked dogs and earned {amount}!",
        "You drove for a ride-share and earned {amount}!",
    ],
    "crime_success_responses": [
        "You robbed a gas station and got {amount}!",
        "You hacked into a database and sold info for {amount}!",
        "You pickpocketed someone for {amount}!",
    ],
    "crime_fail_responses": [
        "You got caught and fined {amount}!",
        "The police caught you. You paid {amount} in bail!",
    ],
    # Advanced gambling
    "roulette_enabled": True,
    "dice_enabled": True,
    "lottery": {"enabled": False, "price": 100, "jackpot": 0, "last_draw": 0, "draw_interval": 86400, "tickets": {}},
    # Stock market
    "stocks": {"enabled": False, "market": {}, "history": {}},
    # Gathering
    "fishing": {
        "enabled": False, "cooldown": 1800, "fish_types": {
            "common_fish": {"emoji": "🐟", "min_value": 10, "max_value": 50, "weight": 50},
            "rare_fish": {"emoji": "🐠", "min_value": 50, "max_value": 200, "weight": 25},
            "legendary_fish": {"emoji": "🐡", "min_value": 200, "max_value": 1000, "weight": 5},
            "treasure": {"emoji": "💰", "min_value": 500, "max_value": 2000, "weight": 2},
            "junk": {"emoji": "🪣", "min_value": 1, "max_value": 10, "weight": 18},
        }
    },
    "mining": {
        "enabled": False, "cooldown": 2400, "ore_types": {
            "coal": {"emoji": "⬛", "min_value": 5, "max_value": 20, "weight": 40},
            "iron": {"emoji": "⬜", "min_value": 20, "max_value": 60, "weight": 30},
            "gold": {"emoji": "🟡", "min_value": 50, "max_value": 200, "weight": 15},
            "diamond": {"emoji": "💎", "min_value": 200, "max_value": 800, "weight": 5},
            "emerald": {"emoji": "🟢", "min_value": 300, "max_value": 1000, "weight": 3},
            "nothing": {"emoji": "💨", "min_value": 0, "max_value": 0, "weight": 7},
        }
    },
    # Crafting
    "crafting": {
        "enabled": False, "recipes": {
            "gold_bar": {"emoji": "🥇", "requires": {"gold": 3}, "value": 500, "description": "A shiny gold bar"},
            "diamond_ring": {"emoji": "💍", "requires": {"diamond": 1, "gold": 1}, "value": 1500, "description": "A diamond ring"},
        }
    },
    # Achievements
    "achievements": {
        "first_daily": {"name": "First Daily", "emoji": "📅", "description": "Claim your first daily", "reward": 50},
        "big_spender": {"name": "Big Spender", "emoji": "💸", "description": "Spend 10,000 coins", "reward": 200},
        "lucky_7": {"name": "Lucky Seven", "emoji": "🎰", "description": "Win slots with 7️⃣", "reward": 777},
        "high_roller": {"name": "High Roller", "emoji": "🎲", "description": "Bet over 10,000 at once", "reward": 500},
        "millionaire": {"name": "Millionaire", "emoji": "💰", "description": "Reach 1,000,000 total balance", "reward": 5000},
        "fisherman": {"name": "Master Fisherman", "emoji": "🎣", "description": "Catch 50 fish", "reward": 300},
        "miner": {"name": "Master Miner", "emoji": "⛏️", "description": "Mine 50 ores", "reward": 300},
    },
    # Income roles
    "income_roles": {},  # role_id -> {amount, interval_hours}
    # Auction
    "auction": {"enabled": False, "listings": {}, "fee_pct": 5},
    # Pets
    "pets": {
        "enabled": True,
        "types": {
            "cat": {"emoji": "🐱", "base_price": 500, "income": 10, "income_interval": 3600},
            "dog": {"emoji": "🐶", "base_price": 500, "income": 10, "income_interval": 3600},
            "bird": {"emoji": "🐦", "base_price": 300, "income": 7, "income_interval": 3600},
            "fish": {"emoji": "🐟", "base_price": 200, "income": 5, "income_interval": 3600},
            "dragon": {"emoji": "🐉", "base_price": 5000, "income": 50, "income_interval": 3600},
            "unicorn": {"emoji": "🦄", "base_price": 10000, "income": 100, "income_interval": 3600},
        },
    },
    # Heist
    "heist": {"cooldown": 3600, "min_bet": 100, "max_players": 10, "vault_base": 10000},
}

ECO_DEFAULTS_MEMBER = {
    "wallet": 0,
    "bank": 0,
    "last_daily": 0,
    "daily_streak": 0,
    "last_weekly": 0,
    "weekly_streak": 0,
    "last_work": 0,
    "last_crime": 0,
    "last_rob": 0,
    "last_fish": 0,
    "last_mine": 0,
    "inventory": {},
    "materials": {},       # material_name -> count
    "pets": {},
    "pet_last_collect": 0,
    "pet_last_feed": 0,
    "transactions": [],
    "gambling_stats": {"won": 0, "lost": 0, "total_wagered": 0, "biggest_win": 0},
    "achievements": [],
    "total_earned": 0,
    "total_spent": 0,
    "fish_caught": 0,
    "ores_mined": 0,
    "stocks_owned": {},   # stock_name -> quantity
}


# ── Views ──────────────────────────────────────────────────────────────────
class ShopView(discord.ui.View):
    def __init__(self, cog, guild, items):
        super().__init__(timeout=120)
        options = []
        for iid, item in list(items.items())[:25]:
            options.append(discord.SelectOption(
                label=item["name"], value=iid,
                description=f"{item['price']:,} coins" + (f" · {item.get('description', '')[:50]}" if item.get("description") else ""),
                emoji=item.get("emoji", "📦"),
            ))
        if options:
            self.sel = discord.ui.Select(placeholder="Buy an item...", options=options)
            self.sel.callback = self.on_select
            self.add_item(self.sel)
        self.cog = cog
        self.guild = guild

    async def on_select(self, interaction: discord.Interaction):
        item_id = self.sel.values[0]
        await self.cog._buy_item(interaction, item_id)


class HeistJoinView(discord.ui.View):
    def __init__(self, cog, heist_id: str, bet: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.heist_id = heist_id
        self.bet = bet
        self.participants = []

    @discord.ui.button(label="🔫 Join Heist!", style=discord.ButtonStyle.danger, custom_id="nexus_eco_heist_join")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.participants:
            return await interaction.response.send_message("Already joined!", ephemeral=True)
        wallet = await self.cog.eco_config.member(interaction.user).wallet()
        if wallet < self.bet:
            return await interaction.response.send_message("Not enough coins!", ephemeral=True)
        self.participants.append(interaction.user.id)
        await interaction.response.send_message(f"🔫 You've joined the heist! ({len(self.participants)} participants)", ephemeral=True)


class BlackjackView(discord.ui.View):
    def __init__(self, cog, ctx, bet: int, player_hand: list, dealer_hand: list, deck: list):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.bet = bet
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.deck = deck
        self.doubled = False
        self.done = False

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return
        self.player_hand.append(self.deck.pop())
        total = bj_value(self.player_hand)
        if total > 21:
            self.done = True
            await self.cog._end_blackjack(interaction, self, "bust")
        elif total == 21:
            self.done = True
            await self.cog._end_blackjack(interaction, self, "stand")
        else:
            embed = self.cog._bj_embed(self.player_hand, self.dealer_hand, self.bet, hidden=True)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return
        self.done = True
        await self.cog._end_blackjack(interaction, self, "stand")

    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.danger, emoji="💰")
    async def double_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            return
        wallet = await self.cog.eco_config.member(self.ctx.author).wallet()
        if wallet < self.bet:
            return await interaction.response.send_message("Not enough for double down.", ephemeral=True)
        self.bet *= 2
        self.doubled = True
        self.player_hand.append(self.deck.pop())
        self.done = True
        await self.cog._end_blackjack(interaction, self, "stand")


class AuctionListView(discord.ui.View):
    def __init__(self, cog, guild, listings):
        super().__init__(timeout=120)
        self.cog = cog
        if not listings:
            return
        options = []
        for lid, listing in list(listings.items())[:25]:
            options.append(discord.SelectOption(
                label=listing.get("item_name", "?"), value=lid,
                description=f"Current bid: {listing.get('current_bid', listing.get('starting_price', 0)):,}",
            ))
        self.sel = discord.ui.Select(placeholder="Bid on an item...", options=options)
        self.sel.callback = self.on_select
        self.add_item(self.sel)

    async def on_select(self, interaction: discord.Interaction):
        listing_id = self.sel.values[0]
        modal = AuctionBidModal(self.cog, listing_id)
        await interaction.response.send_modal(modal)


class AuctionBidModal(discord.ui.Modal):
    def __init__(self, cog, listing_id: str):
        super().__init__(title="Place a Bid")
        self.cog = cog
        self.listing_id = listing_id
        self.amount = discord.ui.TextInput(label="Bid Amount", placeholder="1000", max_length=10)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bid = int(self.amount.value)
        except ValueError:
            return await interaction.response.send_message("Invalid amount.", ephemeral=True)
        await self.cog._place_bid(interaction, self.listing_id, bid)


# ── Blackjack helpers ──────────────────────────────────────────────────────
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

def new_deck():
    deck = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck

def card_str(hand):
    return " ".join(f"`{r}{s}`" for r, s in hand)

def bj_value(hand):
    val = 0
    aces = 0
    for r, s in hand:
        if r in ("J", "Q", "K"):
            val += 10
        elif r == "A":
            val += 11
            aces += 1
        else:
            val += int(r)
    while val > 21 and aces > 0:
        val -= 10
        aces -= 1
    return val


# ── Mixin ──────────────────────────────────────────────────────────────────
class EconomyMixin:
    """Economy mixin — v2 with roulette, dice, lottery, stocks, fishing, mining,
    crafting, achievements, income roles, auction, expanded gambling."""

    def _init_economy(self, bot):
        self.eco_config = Config.get_conf(None, identifier=900008, cog_name="NexusCoreEco")
        self.eco_config.register_guild(**ECO_DEFAULTS_GUILD)
        self.eco_config.register_member(**ECO_DEFAULTS_MEMBER)
        self._active_heists = {}

    # ── Balance helpers ────────────────────────────────────────────────────
    async def _get_balance(self, member: discord.Member) -> tuple[int, int]:
        w = await self.eco_config.member(member).wallet()
        b = await self.eco_config.member(member).bank()
        return w, b

    async def _add_balance(self, member: discord.Member, amount: int, to_bank: bool = False):
        if to_bank:
            current = await self.eco_config.member(member).bank()
            await self.eco_config.member(member).bank.set(current + amount)
        else:
            current = await self.eco_config.member(member).wallet()
            await self.eco_config.member(member).wallet.set(current + amount)
        current_total = await self.eco_config.member(member).total_earned()
        await self.eco_config.member(member).total_earned.set(current_total + max(0, amount))

    async def _remove_balance(self, member: discord.Member, amount: int, from_bank: bool = False):
        if from_bank:
            current = await self.eco_config.member(member).bank()
            await self.eco_config.member(member).bank.set(max(0, current - amount))
        else:
            current = await self.eco_config.member(member).wallet()
            await self.eco_config.member(member).wallet.set(max(0, current - amount))
        current_total = await self.eco_config.member(member).total_spent()
        await self.eco_config.member(member).total_spent.set(current_total + max(0, amount))

    async def _add_transaction(self, member: discord.Member, amount: int, description: str):
        async with self.eco_config.member(member).transactions() as txns:
            txns.append({"amount": amount, "description": description, "at": ts_now()})
            if len(txns) > 100:
                txns[:] = txns[-100:]

    async def _format_amount(self, guild, amount: int) -> str:
        data = await self.eco_config.guild(guild).all()
        return f"{data['currency_emoji']} {amount:,}"

    async def _check_achievement(self, member: discord.Member, achievement_id: str):
        """Check and award an achievement."""
        current = await self.eco_config.member(member).achievements()
        if achievement_id in current:
            return
        data = await self.eco_config.guild(member.guild).all()
        ach = data.get("achievements", {}).get(achievement_id)
        if not ach:
            return
        async with self.eco_config.member(member).achievements() as achs:
            achs.append(achievement_id)
        reward = ach.get("reward", 0)
        if reward:
            await self._add_balance(member, reward)
        await safe_dm(member, embed=discord.Embed(
            title=f"🏆 Achievement Unlocked!",
            description=f"{ach.get('emoji', '🏆')} **{ach['name']}**\n{ach.get('description', '')}\nReward: {reward:,} coins",
            colour=Clr.ECO))

    # ── Daily/Weekly ───────────────────────────────────────────────────────
    async def _daily(self, ctx):
        member = ctx.author
        data = await self.eco_config.guild(ctx.guild).all()
        last = await self.eco_config.member(member).last_daily()
        streak = await self.eco_config.member(member).daily_streak()
        now = ts_now()
        if now - last < 72000:  # 20h to allow some flexibility
            remaining = 72000 - (now - last)
            return await ctx.send(embed=err_embed(f"Daily cooldown: {duration_str(remaining)}"))

        if now - last < 172800:  # 48h to maintain streak
            streak += 1
        else:
            streak = 1
        await self.eco_config.member(member).daily_streak.set(streak)
        await self.eco_config.member(member).last_daily.set(now)

        base = data["daily_amount"]
        bonus = data.get("daily_streak_bonus", 10) * (streak - 1)
        total = base + bonus
        await self._add_balance(member, total)
        await self._add_transaction(member, total, f"Daily (streak {streak})")

        embed = discord.Embed(title="📅 Daily Reward", colour=Clr.ECO)
        embed.description = f"You received **{await self._format_amount(ctx.guild, total)}**!"
        if bonus > 0:
            embed.add_field(name="Streak Bonus", value=f"+{bonus:,} (🔥 {streak} day streak)", inline=True)
        await ctx.send(embed=embed)
        await self._check_achievement(member, "first_daily")

    async def _weekly(self, ctx):
        member = ctx.author
        data = await self.eco_config.guild(ctx.guild).all()
        last = await self.eco_config.member(member).last_weekly()
        streak = await self.eco_config.member(member).weekly_streak()
        now = ts_now()
        if now - last < 604800:
            remaining = 604800 - (now - last)
            return await ctx.send(embed=err_embed(f"Weekly cooldown: {duration_str(remaining)}"))

        if now - last < 1209600:
            streak += 1
        else:
            streak = 1
        await self.eco_config.member(member).weekly_streak.set(streak)
        await self.eco_config.member(member).last_weekly.set(now)

        base = data["weekly_amount"]
        bonus = data.get("weekly_streak_bonus", 50) * (streak - 1)
        total = base + bonus
        await self._add_balance(member, total)
        await self._add_transaction(member, total, f"Weekly (streak {streak})")

        embed = discord.Embed(title="📅 Weekly Reward", colour=Clr.ECO)
        embed.description = f"You received **{await self._format_amount(ctx.guild, total)}**!"
        if bonus:
            embed.add_field(name="Streak Bonus", value=f"+{bonus:,} (🔥 {streak} week streak)", inline=True)
        await ctx.send(embed=embed)

    # ── Work/Crime/Rob ─────────────────────────────────────────────────────
    async def _work(self, ctx):
        member = ctx.author
        data = await self.eco_config.guild(ctx.guild).all()
        last = await self.eco_config.member(member).last_work()
        if ts_now() - last < data["work_cooldown"]:
            remaining = data["work_cooldown"] - (ts_now() - last)
            return await ctx.send(embed=err_embed(f"Work cooldown: {duration_str(remaining)}"))

        amount = random.randint(data["work_min"], data["work_max"])
        await self.eco_config.member(member).last_work.set(ts_now())
        await self._add_balance(member, amount)
        await self._add_transaction(member, amount, "Work")

        responses = data.get("work_responses", ["You worked and earned {amount}!"])
        msg = random.choice(responses).format(amount=await self._format_amount(ctx.guild, amount))
        await ctx.send(embed=ok_embed(msg))

    async def _crime(self, ctx):
        member = ctx.author
        data = await self.eco_config.guild(ctx.guild).all()
        last = await self.eco_config.member(member).last_crime()
        if ts_now() - last < data["crime_cooldown"]:
            remaining = data["crime_cooldown"] - (ts_now() - last)
            return await ctx.send(embed=err_embed(f"Crime cooldown: {duration_str(remaining)}"))

        await self.eco_config.member(member).last_crime.set(ts_now())
        if random.randint(1, 100) <= data["crime_fail_chance"]:
            fine = random.randint(data["crime_min"], data["crime_max"]) * data.get("crime_fine_pct", 30) // 100
            await self._remove_balance(member, fine)
            await self._add_transaction(member, -fine, "Crime (failed)")
            responses = data.get("crime_fail_responses", ["You got caught and paid {amount}!"])
            msg = random.choice(responses).format(amount=await self._format_amount(ctx.guild, fine))
            await ctx.send(embed=err_embed(msg))
        else:
            amount = random.randint(data["crime_min"], data["crime_max"])
            await self._add_balance(member, amount)
            await self._add_transaction(member, amount, "Crime (success)")
            responses = data.get("crime_success_responses", ["You got away with {amount}!"])
            msg = random.choice(responses).format(amount=await self._format_amount(ctx.guild, amount))
            await ctx.send(embed=ok_embed(msg))

    async def _rob(self, ctx, target: discord.Member):
        data = await self.eco_config.guild(ctx.guild).all()
        if not data["rob_enabled"]:
            return await ctx.send(embed=err_embed("Robbing is disabled."))
        if target.id == ctx.author.id:
            return await ctx.send(embed=err_embed("Can't rob yourself."))
        if target.bot:
            return await ctx.send(embed=err_embed("Can't rob bots."))
        last = await self.eco_config.member(ctx.author).last_rob()
        if ts_now() - last < data["rob_cooldown"]:
            remaining = data["rob_cooldown"] - (ts_now() - last)
            return await ctx.send(embed=err_embed(f"Rob cooldown: {duration_str(remaining)}"))
        target_wallet = await self.eco_config.member(target).wallet()
        if target_wallet < data["rob_min_wallet"]:
            return await ctx.send(embed=err_embed(f"{target.display_name} doesn't have enough to rob."))

        await self.eco_config.member(ctx.author).last_rob.set(ts_now())
        if random.randint(1, 100) <= data["rob_fail_chance"]:
            fine = min(target_wallet, random.randint(50, 200))
            await self._remove_balance(ctx.author, fine)
            await self._add_balance(target, fine)
            await ctx.send(embed=err_embed(f"You got caught and paid {target.mention} {fine:,} coins."))
        else:
            max_rob = int(target_wallet * data["rob_max_pct"] / 100)
            stolen = random.randint(1, max(1, max_rob))
            await self._remove_balance(target, stolen)
            await self._add_balance(ctx.author, stolen)
            await self._add_transaction(ctx.author, stolen, f"Robbed {target}")
            await self._add_transaction(target, -stolen, f"Robbed by {ctx.author}")
            await ctx.send(embed=ok_embed(f"You stole **{stolen:,}** from {target.mention}!"))

    # ── Bank ───────────────────────────────────────────────────────────────
    async def _deposit(self, ctx, amount: int):
        wallet = await self.eco_config.member(ctx.author).wallet()
        if amount > wallet or amount <= 0:
            return await ctx.send(embed=err_embed("Invalid amount."))
        data = await self.eco_config.guild(ctx.guild).all()
        max_bank = data.get("max_bank", 0)
        bank = await self.eco_config.member(ctx.author).bank()
        if max_bank and bank + amount > max_bank:
            amount = max_bank - bank
            if amount <= 0:
                return await ctx.send(embed=err_embed("Bank is full."))
        await self._remove_balance(ctx.author, amount)
        await self._add_balance(ctx.author, amount, to_bank=True)
        await ctx.send(embed=ok_embed(f"Deposited **{amount:,}**"))

    async def _withdraw(self, ctx, amount: int):
        bank = await self.eco_config.member(ctx.author).bank()
        if amount > bank or amount <= 0:
            return await ctx.send(embed=err_embed("Invalid amount."))
        await self._remove_balance(ctx.author, amount, from_bank=True)
        await self._add_balance(ctx.author, amount)
        await ctx.send(embed=ok_embed(f"Withdrew **{amount:,}**"))

    # ── Gambling ───────────────────────────────────────────────────────────
    async def _validate_bet(self, ctx, bet: int) -> bool:
        data = await self.eco_config.guild(ctx.guild).all()
        if bet < data["min_bet"]:
            await ctx.send(embed=err_embed(f"Minimum bet: {data['min_bet']:,}"))
            return False
        if data["max_bet"] and bet > data["max_bet"]:
            await ctx.send(embed=err_embed(f"Maximum bet: {data['max_bet']:,}"))
            return False
        wallet = await self.eco_config.member(ctx.author).wallet()
        if bet > wallet:
            await ctx.send(embed=err_embed("Not enough coins."))
            return False
        return True

    async def _update_gambling_stats(self, member, won: bool, amount: int, wagered: int):
        async with self.eco_config.member(member).gambling_stats() as stats:
            if won:
                stats["won"] = stats.get("won", 0) + amount
                stats["biggest_win"] = max(stats.get("biggest_win", 0), amount)
            else:
                stats["lost"] = stats.get("lost", 0) + amount
            stats["total_wagered"] = stats.get("total_wagered", 0) + wagered
        if wagered >= 10000:
            await self._check_achievement(member, "high_roller")

    async def _coinflip(self, ctx, bet: int, choice: str):
        if not await self._validate_bet(ctx, bet):
            return
        choice = choice.lower()
        if choice not in ("heads", "tails", "h", "t"):
            return await ctx.send(embed=err_embed("Choose `heads` or `tails`."))
        result = random.choice(["heads", "tails"])
        won = choice[0] == result[0]
        emoji = "🪙"
        if won:
            await self._add_balance(ctx.author, bet)
            await self._add_transaction(ctx.author, bet, "Coinflip (won)")
            await self._update_gambling_stats(ctx.author, True, bet, bet)
            embed = discord.Embed(title=f"{emoji} Coinflip — {result.title()}", description=f"You won **{bet:,}**! 🎉", colour=Clr.SUCCESS)
        else:
            await self._remove_balance(ctx.author, bet)
            await self._add_transaction(ctx.author, -bet, "Coinflip (lost)")
            await self._update_gambling_stats(ctx.author, False, bet, bet)
            embed = discord.Embed(title=f"{emoji} Coinflip — {result.title()}", description=f"You lost **{bet:,}**.", colour=Clr.ERROR)
        await ctx.send(embed=embed)

    async def _slots(self, ctx, bet: int):
        if not await self._validate_bet(ctx, bet):
            return
        data = await self.eco_config.guild(ctx.guild).all()
        emojis = data.get("slots_emojis", ["🍎", "🍊", "🍇", "🍒", "🍋", "💎", "7️⃣"])
        reels = [random.choice(emojis) for _ in range(3)]
        display = f"{'  |  '.join(reels)}"
        if reels[0] == reels[1] == reels[2]:
            if reels[0] == "7️⃣":
                mult = 10
                await self._check_achievement(ctx.author, "lucky_7")
            elif reels[0] == "💎":
                mult = 5
            else:
                mult = 3
            winnings = bet * mult
            await self._add_balance(ctx.author, winnings)
            await self._add_transaction(ctx.author, winnings, f"Slots ({mult}x)")
            await self._update_gambling_stats(ctx.author, True, winnings, bet)
            embed = discord.Embed(title="🎰 JACKPOT!", description=f"{display}\n\nYou won **{winnings:,}** ({mult}x)! 🎉", colour=Clr.SUCCESS)
        elif reels[0] == reels[1] or reels[1] == reels[2]:
            winnings = int(bet * 1.5)
            await self._add_balance(ctx.author, winnings - bet)
            await self._add_transaction(ctx.author, winnings - bet, "Slots (1.5x)")
            await self._update_gambling_stats(ctx.author, True, winnings - bet, bet)
            embed = discord.Embed(title="🎰 Slots", description=f"{display}\n\nTwo match! +**{winnings - bet:,}**", colour=Clr.ECO)
        else:
            await self._remove_balance(ctx.author, bet)
            await self._add_transaction(ctx.author, -bet, "Slots (lost)")
            await self._update_gambling_stats(ctx.author, False, bet, bet)
            embed = discord.Embed(title="🎰 Slots", description=f"{display}\n\nNo match. You lost **{bet:,}**.", colour=Clr.ERROR)
        await ctx.send(embed=embed)

    async def _blackjack(self, ctx, bet: int):
        if not await self._validate_bet(ctx, bet):
            return
        deck = new_deck()
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]
        await self._remove_balance(ctx.author, bet)
        if bj_value(player_hand) == 21:
            winnings = int(bet * 2.5)
            await self._add_balance(ctx.author, winnings)
            await self._add_transaction(ctx.author, winnings - bet, "Blackjack (natural)")
            await self._update_gambling_stats(ctx.author, True, winnings - bet, bet)
            embed = self._bj_embed(player_hand, dealer_hand, bet, hidden=False)
            embed.title = "🃏 BLACKJACK!"
            embed.description += f"\n\n🎉 Natural 21! You won **{winnings - bet:,}**!"
            embed.colour = Clr.SUCCESS
            return await ctx.send(embed=embed)
        view = BlackjackView(self, ctx, bet, player_hand, dealer_hand, deck)
        embed = self._bj_embed(player_hand, dealer_hand, bet, hidden=True)
        await ctx.send(embed=embed, view=view)

    def _bj_embed(self, player_hand, dealer_hand, bet, hidden=True):
        dealer_show = f"{card_str([dealer_hand[0]])} `??`" if hidden else card_str(dealer_hand)
        dealer_val = bj_value([dealer_hand[0]]) if hidden else bj_value(dealer_hand)
        player_val = bj_value(player_hand)
        embed = discord.Embed(title="🃏 Blackjack", colour=Clr.ECO)
        embed.add_field(name=f"Dealer ({dealer_val}{'?' if hidden else ''})", value=dealer_show, inline=False)
        embed.add_field(name=f"You ({player_val})", value=card_str(player_hand), inline=False)
        embed.set_footer(text=f"Bet: {bet:,}")
        return embed

    async def _end_blackjack(self, interaction, view: BlackjackView, action: str):
        bet = view.bet
        player_hand = view.player_hand
        dealer_hand = view.dealer_hand
        deck = view.deck
        player_val = bj_value(player_hand)

        if action == "bust":
            await self._add_transaction(view.ctx.author, -bet, "Blackjack (bust)")
            await self._update_gambling_stats(view.ctx.author, False, bet, bet)
            embed = self._bj_embed(player_hand, dealer_hand, bet, hidden=False)
            embed.description = f"💥 Bust! ({player_val}) You lost **{bet:,}**."
            embed.colour = Clr.ERROR
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except Exception:
                pass
            return

        # Dealer plays
        while bj_value(dealer_hand) < 17:
            dealer_hand.append(deck.pop())
        dealer_val = bj_value(dealer_hand)

        embed = self._bj_embed(player_hand, dealer_hand, bet, hidden=False)
        if dealer_val > 21 or player_val > dealer_val:
            winnings = bet * 2
            await self._add_balance(view.ctx.author, winnings)
            await self._add_transaction(view.ctx.author, winnings - bet, "Blackjack (won)")
            await self._update_gambling_stats(view.ctx.author, True, winnings - bet, bet)
            embed.description = f"🎉 You won **{winnings - bet:,}**!"
            embed.colour = Clr.SUCCESS
        elif player_val == dealer_val:
            await self._add_balance(view.ctx.author, bet)
            embed.description = "🤝 Push! Bet returned."
            embed.colour = Clr.ECO
        else:
            await self._add_transaction(view.ctx.author, -bet, "Blackjack (lost)")
            await self._update_gambling_stats(view.ctx.author, False, bet, bet)
            embed.description = f"💔 Dealer wins. You lost **{bet:,}**."
            embed.colour = Clr.ERROR
        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            pass

    # ── Roulette ───────────────────────────────────────────────────────────
    async def _roulette(self, ctx, bet: int, choice: str):
        if not await self._validate_bet(ctx, bet):
            return
        result = random.randint(0, 36)
        is_red = result in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
        is_black = result != 0 and not is_red
        colour = "🔴" if is_red else ("⚫" if is_black else "🟢")
        multiplier = 0
        choice_lower = choice.lower()
        if choice_lower == "red" and is_red:
            multiplier = 2
        elif choice_lower == "black" and is_black:
            multiplier = 2
        elif choice_lower in ("even", "odd"):
            if result != 0:
                if (choice_lower == "even" and result % 2 == 0) or (choice_lower == "odd" and result % 2 == 1):
                    multiplier = 2
        elif choice_lower in ("high", "low"):
            if result != 0:
                if (choice_lower == "low" and 1 <= result <= 18) or (choice_lower == "high" and 19 <= result <= 36):
                    multiplier = 2
        else:
            try:
                num = int(choice)
                if num == result:
                    multiplier = 36
            except ValueError:
                return await ctx.send(embed=err_embed("Choose: red, black, even, odd, high, low, or a number 0-36"))

        if multiplier:
            winnings = bet * multiplier
            await self._add_balance(ctx.author, winnings - bet)
            await self._add_transaction(ctx.author, winnings - bet, f"Roulette ({multiplier}x)")
            await self._update_gambling_stats(ctx.author, True, winnings - bet, bet)
            embed = discord.Embed(title=f"🎰 Roulette — {colour} {result}", description=f"You won **{winnings:,}** ({multiplier}x)! 🎉", colour=Clr.SUCCESS)
        else:
            await self._remove_balance(ctx.author, bet)
            await self._add_transaction(ctx.author, -bet, "Roulette (lost)")
            await self._update_gambling_stats(ctx.author, False, bet, bet)
            embed = discord.Embed(title=f"🎰 Roulette — {colour} {result}", description=f"You lost **{bet:,}**.", colour=Clr.ERROR)
        await ctx.send(embed=embed)

    # ── Dice ───────────────────────────────────────────────────────────────
    async def _dice(self, ctx, bet: int, guess: int):
        if not await self._validate_bet(ctx, bet):
            return
        if not 2 <= guess <= 12:
            return await ctx.send(embed=err_embed("Guess a total between 2-12."))
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        if total == guess:
            odds_map = {2: 36, 3: 18, 4: 12, 5: 9, 6: 7, 7: 6, 8: 7, 9: 9, 10: 12, 11: 18, 12: 36}
            mult = odds_map.get(guess, 6)
            winnings = bet * mult
            await self._add_balance(ctx.author, winnings - bet)
            await self._add_transaction(ctx.author, winnings - bet, f"Dice ({mult}x)")
            await self._update_gambling_stats(ctx.author, True, winnings - bet, bet)
            embed = discord.Embed(title=f"🎲 {d1} + {d2} = {total}", description=f"🎉 Exact match! Won **{winnings:,}** ({mult}x)", colour=Clr.SUCCESS)
        else:
            await self._remove_balance(ctx.author, bet)
            await self._add_transaction(ctx.author, -bet, "Dice (lost)")
            await self._update_gambling_stats(ctx.author, False, bet, bet)
            embed = discord.Embed(title=f"🎲 {d1} + {d2} = {total}", description=f"You guessed {guess}. Lost **{bet:,}**.", colour=Clr.ERROR)
        await ctx.send(embed=embed)

    # ── Fishing ────────────────────────────────────────────────────────────
    async def _fish(self, ctx):
        data = await self.eco_config.guild(ctx.guild).all()
        fishing = data.get("fishing", {})
        if not fishing.get("enabled"):
            return await ctx.send(embed=err_embed("Fishing is disabled."))
        last = await self.eco_config.member(ctx.author).last_fish()
        if ts_now() - last < fishing.get("cooldown", 1800):
            remaining = fishing.get("cooldown", 1800) - (ts_now() - last)
            return await ctx.send(embed=err_embed(f"Fishing cooldown: {duration_str(remaining)}"))

        await self.eco_config.member(ctx.author).last_fish.set(ts_now())
        types = fishing.get("fish_types", {})
        weights = [v["weight"] for v in types.values()]
        names = list(types.keys())
        caught_name = random.choices(names, weights=weights, k=1)[0]
        caught = types[caught_name]
        value = random.randint(caught["min_value"], caught["max_value"])
        await self._add_balance(ctx.author, value)
        await self._add_transaction(ctx.author, value, f"Fishing ({caught_name})")

        count = await self.eco_config.member(ctx.author).fish_caught()
        await self.eco_config.member(ctx.author).fish_caught.set(count + 1)
        if count + 1 >= 50:
            await self._check_achievement(ctx.author, "fisherman")

        embed = discord.Embed(
            title="🎣 Fishing",
            description=f"You caught a {caught['emoji']} **{caught_name.replace('_', ' ').title()}**!\nSold for **{value:,}** coins.",
            colour=Clr.ECO,
        )
        await ctx.send(embed=embed)

    # ── Mining ─────────────────────────────────────────────────────────────
    async def _mine(self, ctx):
        data = await self.eco_config.guild(ctx.guild).all()
        mining = data.get("mining", {})
        if not mining.get("enabled"):
            return await ctx.send(embed=err_embed("Mining is disabled."))
        last = await self.eco_config.member(ctx.author).last_mine()
        if ts_now() - last < mining.get("cooldown", 2400):
            remaining = mining.get("cooldown", 2400) - (ts_now() - last)
            return await ctx.send(embed=err_embed(f"Mining cooldown: {duration_str(remaining)}"))

        await self.eco_config.member(ctx.author).last_mine.set(ts_now())
        types = mining.get("ore_types", {})
        weights = [v["weight"] for v in types.values()]
        names = list(types.keys())
        mined_name = random.choices(names, weights=weights, k=1)[0]
        mined = types[mined_name]
        value = random.randint(mined["min_value"], mined["max_value"])

        # Store materials for crafting
        if mined_name != "nothing":
            async with self.eco_config.member(ctx.author).materials() as mats:
                mats[mined_name] = mats.get(mined_name, 0) + 1

        await self._add_balance(ctx.author, value)
        await self._add_transaction(ctx.author, value, f"Mining ({mined_name})")

        count = await self.eco_config.member(ctx.author).ores_mined()
        await self.eco_config.member(ctx.author).ores_mined.set(count + 1)
        if count + 1 >= 50:
            await self._check_achievement(ctx.author, "miner")

        embed = discord.Embed(
            title="⛏️ Mining",
            description=f"You mined {mined['emoji']} **{mined_name.replace('_', ' ').title()}**!"
                        + (f"\nSold for **{value:,}** coins." if value else "\nNothing valuable..."),
            colour=Clr.ECO,
        )
        await ctx.send(embed=embed)

    # ── Crafting ───────────────────────────────────────────────────────────
    async def _craft(self, ctx, recipe_name: str):
        data = await self.eco_config.guild(ctx.guild).all()
        crafting = data.get("crafting", {})
        if not crafting.get("enabled"):
            return await ctx.send(embed=err_embed("Crafting is disabled."))
        recipe = crafting.get("recipes", {}).get(recipe_name.lower())
        if not recipe:
            recipes = crafting.get("recipes", {})
            recipe_list = "\n".join(f"{v.get('emoji', '📦')} **{k}** — requires: {', '.join(f'{c}x {m}' for m, c in v['requires'].items())}" for k, v in recipes.items())
            return await ctx.send(embed=info_embed(f"Available recipes:\n{recipe_list}"))

        materials = await self.eco_config.member(ctx.author).materials()
        for mat, count in recipe["requires"].items():
            if materials.get(mat, 0) < count:
                return await ctx.send(embed=err_embed(f"Need {count}x {mat}, you have {materials.get(mat, 0)}."))

        async with self.eco_config.member(ctx.author).materials() as mats:
            for mat, count in recipe["requires"].items():
                mats[mat] -= count

        value = recipe.get("value", 0)
        await self._add_balance(ctx.author, value)
        await self._add_transaction(ctx.author, value, f"Crafted {recipe_name}")

        embed = discord.Embed(
            title="🔨 Crafted!",
            description=f"You crafted {recipe.get('emoji', '📦')} **{recipe_name.replace('_', ' ').title()}**!\n{recipe.get('description', '')}\nValue: **{value:,}** coins",
            colour=Clr.ECO,
        )
        await ctx.send(embed=embed)

    # ── Shop ───────────────────────────────────────────────────────────────
    async def _buy_item(self, interaction, item_id: str):
        guild = interaction.guild
        data = await self.eco_config.guild(guild).all()
        item = data["shop_items"].get(item_id)
        if not item:
            return await interaction.response.send_message("Item not found.", ephemeral=True)

        wallet = await self.eco_config.member(interaction.user).wallet()
        if wallet < item["price"]:
            return await interaction.response.send_message("Not enough coins.", ephemeral=True)

        if item.get("stock", -1) == 0:
            return await interaction.response.send_message("Out of stock.", ephemeral=True)

        inv = await self.eco_config.member(interaction.user).inventory()
        if item.get("max_per_user", 0) > 0:
            if inv.get(item_id, 0) >= item["max_per_user"]:
                return await interaction.response.send_message("You already own the max.", ephemeral=True)

        await self._remove_balance(interaction.user, item["price"])
        async with self.eco_config.member(interaction.user).inventory() as inv:
            inv[item_id] = inv.get(item_id, 0) + 1

        if item.get("stock", -1) > 0:
            async with self.eco_config.guild(guild).shop_items() as items:
                if item_id in items:
                    items[item_id]["stock"] -= 1

        # Role item
        if item.get("type") == "role" and item.get("role_id"):
            role = guild.get_role(item["role_id"])
            if role:
                try:
                    await interaction.user.add_roles(role, reason="NexusCore shop purchase")
                except discord.HTTPException:
                    pass

        await self._add_transaction(interaction.user, -item["price"], f"Bought {item['name']}")
        await interaction.response.send_message(f"✅ Purchased **{item['name']}** for {item['price']:,}!", ephemeral=True)

        total_spent = await self.eco_config.member(interaction.user).total_spent()
        if total_spent >= 10000:
            await self._check_achievement(interaction.user, "big_spender")

    # ── Pets ───────────────────────────────────────────────────────────────
    async def _buy_pet(self, ctx, pet_type: str, name: str):
        data = await self.eco_config.guild(ctx.guild).all()
        pets_config = data.get("pets", {})
        if not pets_config.get("enabled"):
            return await ctx.send(embed=err_embed("Pets are disabled."))
        types = pets_config.get("types", {})
        if pet_type not in types:
            return await ctx.send(embed=err_embed(f"Available types: {', '.join(types.keys())}"))
        pet_info = types[pet_type]
        price = pet_info["base_price"]
        wallet = await self.eco_config.member(ctx.author).wallet()
        if wallet < price:
            return await ctx.send(embed=err_embed(f"Not enough! Need {price:,}."))
        pets = await self.eco_config.member(ctx.author).pets()
        if len(pets) >= 5:
            return await ctx.send(embed=err_embed("Max 5 pets."))
        if name.lower() in [n.lower() for n in pets]:
            return await ctx.send(embed=err_embed("You already have a pet with that name."))
        await self._remove_balance(ctx.author, price)
        async with self.eco_config.member(ctx.author).pets() as p:
            p[name] = {"type": pet_type, "level": 1, "xp": 0, "happiness": 100, "last_feed": 0}
        await ctx.send(embed=ok_embed(f"{pet_info['emoji']} **{name}** the {pet_type} has joined you!"))

    async def _feed_pet(self, ctx, name: str):
        pets = await self.eco_config.member(ctx.author).pets()
        if name not in pets:
            return await ctx.send(embed=err_embed("Pet not found."))
        pet = pets[name]
        if ts_now() - pet.get("last_feed", 0) < 3600:
            return await ctx.send(embed=err_embed("Pet isn't hungry yet."))
        cost = 50 * pet.get("level", 1)
        wallet = await self.eco_config.member(ctx.author).wallet()
        if wallet < cost:
            return await ctx.send(embed=err_embed(f"Need {cost:,} to feed."))
        await self._remove_balance(ctx.author, cost)
        async with self.eco_config.member(ctx.author).pets() as p:
            if name in p:
                p[name]["happiness"] = min(100, p[name].get("happiness", 50) + 20)
                p[name]["xp"] = p[name].get("xp", 0) + 10
                p[name]["last_feed"] = ts_now()
                if p[name]["xp"] >= p[name].get("level", 1) * 50:
                    p[name]["level"] += 1
                    p[name]["xp"] = 0
                    await ctx.send(embed=ok_embed(f"🎉 **{name}** leveled up to Lv.{p[name]['level']}!"))
        await ctx.send(embed=ok_embed(f"Fed **{name}**! (-{cost:,} coins, ❤️ +20%)"))

    async def _pet_collect(self, ctx):
        data = await self.eco_config.guild(ctx.guild).all()
        pets_config = data.get("pets", {})
        types = pets_config.get("types", {})
        pets = await self.eco_config.member(ctx.author).pets()
        last_collect = await self.eco_config.member(ctx.author).pet_last_collect()
        if ts_now() - last_collect < 3600:
            remaining = 3600 - (ts_now() - last_collect)
            return await ctx.send(embed=err_embed(f"Collect cooldown: {duration_str(remaining)}"))

        total = 0
        breakdown = []
        for name, pet in pets.items():
            pt = types.get(pet["type"], {})
            base = pt.get("income", 10)
            income = base * pet.get("level", 1) * (pet.get("happiness", 50) / 100)
            income = int(income)
            if income > 0:
                total += income
                breakdown.append(f"{pt.get('emoji', '🐾')} **{name}** — +{income:,}")

        if not total:
            return await ctx.send(embed=err_embed("No pet income to collect."))

        await self._add_balance(ctx.author, total)
        await self.eco_config.member(ctx.author).pet_last_collect.set(ts_now())
        await self._add_transaction(ctx.author, total, "Pet income")

        embed = discord.Embed(title="🐾 Pet Income Collected!", colour=Clr.ECO)
        embed.description = f"Total: **{total:,}**\n" + "\n".join(breakdown)
        await ctx.send(embed=embed)

    # ── Heist ──────────────────────────────────────────────────────────────
    async def _start_heist(self, ctx, bet: int):
        if not await self._validate_bet(ctx, bet):
            return
        gid = ctx.guild.id
        if gid in self._active_heists:
            return await ctx.send(embed=err_embed("A heist is already in progress!"))
        data = await self.eco_config.guild(ctx.guild).all()
        heist_config = data.get("heist", {})
        min_bet = heist_config.get("min_bet", 100)
        if bet < min_bet:
            return await ctx.send(embed=err_embed(f"Minimum heist bet: {min_bet:,}"))

        heist_id = short_id(8)
        self._active_heists[gid] = heist_id
        view = HeistJoinView(self, heist_id, bet)
        view.participants = [ctx.author.id]
        await self._remove_balance(ctx.author, bet)

        embed = discord.Embed(
            title="🔫 Heist Starting!", colour=Clr.ECO,
            description=f"{ctx.author.mention} is planning a heist!\nBet: **{bet:,}** coins\nClick to join! (60s to join)",
        )
        msg = await ctx.send(embed=embed, view=view)
        await asyncio.sleep(60)
        view.stop()

        participants = view.participants
        for uid in participants:
            if uid != ctx.author.id:
                member = ctx.guild.get_member(uid)
                if member:
                    await self._remove_balance(member, bet)

        vault = heist_config.get("vault_base", 10000) + (bet * len(participants))
        success_chance = min(90, 30 + (len(participants) * 10))
        success = random.randint(1, 100) <= success_chance

        if success:
            share = vault // len(participants)
            winners = []
            for uid in participants:
                member = ctx.guild.get_member(uid)
                if member:
                    await self._add_balance(member, share)
                    await self._add_transaction(member, share - bet, "Heist (won)")
                    winners.append(member.mention)
            embed = discord.Embed(
                title="🔫 Heist Successful!", colour=Clr.SUCCESS,
                description=f"The crew got away with **{vault:,}** coins!\nEach member gets **{share:,}**\n\nParticipants: {', '.join(winners)}",
            )
        else:
            losers = []
            for uid in participants:
                member = ctx.guild.get_member(uid)
                if member:
                    await self._add_transaction(member, -bet, "Heist (failed)")
                    losers.append(member.mention)
            embed = discord.Embed(
                title="🔫 Heist Failed!", colour=Clr.ERROR,
                description=f"The police caught the crew! Everyone lost **{bet:,}** coins.\n\nParticipants: {', '.join(losers)}",
            )

        del self._active_heists[gid]
        await ctx.send(embed=embed)

    # ── Auction ────────────────────────────────────────────────────────────
    async def _create_auction(self, ctx, item_name: str, starting_price: int, duration: int):
        data = await self.eco_config.guild(ctx.guild).all()
        if not data.get("auction", {}).get("enabled"):
            return await ctx.send(embed=err_embed("Auction house is disabled."))
        listing_id = short_id(8)
        listing = {
            "seller_id": ctx.author.id, "item_name": item_name,
            "starting_price": starting_price, "current_bid": starting_price,
            "highest_bidder": None, "ends_at": ts_now() + duration,
            "ended": False,
        }
        async with self.eco_config.guild(ctx.guild).auction() as auction:
            auction.setdefault("listings", {})[listing_id] = listing
        await ctx.send(embed=ok_embed(f"Auction listed: **{item_name}** starting at {starting_price:,} (ID: `{listing_id}`)"))

    async def _place_bid(self, interaction, listing_id: str, bid: int):
        guild = interaction.guild
        data = await self.eco_config.guild(guild).all()
        listing = data.get("auction", {}).get("listings", {}).get(listing_id)
        if not listing:
            return await interaction.response.send_message("Listing not found.", ephemeral=True)
        if listing.get("ended"):
            return await interaction.response.send_message("Auction ended.", ephemeral=True)
        if bid <= listing.get("current_bid", 0):
            return await interaction.response.send_message(f"Bid must be higher than {listing['current_bid']:,}.", ephemeral=True)
        wallet = await self.eco_config.member(interaction.user).wallet()
        if wallet < bid:
            return await interaction.response.send_message("Not enough coins.", ephemeral=True)

        # Refund previous bidder
        prev = listing.get("highest_bidder")
        if prev:
            prev_member = guild.get_member(prev)
            if prev_member:
                await self._add_balance(prev_member, listing["current_bid"])

        await self._remove_balance(interaction.user, bid)
        async with self.eco_config.guild(guild).auction() as auction:
            if listing_id in auction.get("listings", {}):
                auction["listings"][listing_id]["current_bid"] = bid
                auction["listings"][listing_id]["highest_bidder"] = interaction.user.id

        await interaction.response.send_message(f"Bid of **{bid:,}** placed!", ephemeral=True)

    # ── Income roles loop ──────────────────────────────────────────────────
    async def _income_role_loop(self):
        """Give passive income based on roles."""
        while True:
            try:
                for guild in self.bot.guilds:
                    data = await self.eco_config.guild(guild).all()
                    income_roles = data.get("income_roles", {})
                    for role_id_str, config in income_roles.items():
                        role = guild.get_role(int(role_id_str))
                        if not role:
                            continue
                        for member in role.members:
                            if not member.bot:
                                await self._add_balance(member, config["amount"])
            except Exception:
                pass
            await asyncio.sleep(3600)  # Check every hour

    # ── Millionaire check ──────────────────────────────────────────────────
    async def _check_millionaire(self, member: discord.Member):
        w, b = await self._get_balance(member)
        if w + b >= 1000000:
            await self._check_achievement(member, "millionaire")
