import discord
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient
import re
import os
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import aiohttp
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

GUILD = discord.Object(id=1341366670417203293)

webhook_url = f"{os.getenv('WEBHOOK_DAILY')}?wait=true"
MONGO_URI = os.getenv("MONGO_URI") 

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client.tasks_db 
user_tasks_daily_collection = db.user_tasks
daily_task_messages_collection = db.daily_task_messages

date_today = datetime.datetime.now().strftime("%d-%m-%Y (%A)")

daily_channel_id = 1343804854056779869

scheduler = AsyncIOScheduler()

async def send_daily_reminders():
    await bot.wait_until_ready()
    channel = bot.get_channel(daily_channel_id)
    if channel:
        await channel.send("Reminder: Kindly update your everyday tasks by 10 pm!")


class CompletionSelect(discord.ui.Select):
    def __init__(self, user_id, options):
        super().__init__(placeholder="Select tasks to mark as complete", min_values=1, max_values=len(options), options=options)
        self.user_id = user_id
        self.task_messages = list(daily_task_messages_collection.find({
            "user_id": self.user_id,
            "date_today": date_today
            }))

    async def callback(self, interaction: discord.Interaction):
        selected_task_names = [re.search(": .+", label).group()[2:] for label in self.values]

        user_tasks_daily_collection.update_many(
            {"user_id": self.user_id, "task_name": {"$in": selected_task_names}, "date_today": date_today},
            {"$set": {"completed": True}}
        )

        # Update the message
        message_id = self.task_messages[0]["task_messages"]
        if message_id:
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, session=session) 

                try:
                    message = await webhook.fetch_message(message_id)

                    if message:
                        embed = message.embeds[0]
                        embed.clear_fields()

                        user_tasks = list(user_tasks_daily_collection.find({"user_id": self.user_id, "date_today": date_today}))
                        completed_count = sum(task.get("completed", False) for task in user_tasks)
                        total_tasks = len(user_tasks)
                        completion_percentage = int((completed_count / total_tasks) * 100) if total_tasks > 0 else 0

                        for i, task in enumerate(user_tasks):
                            checkmark = "✅" if task.get("completed", False) else ""
                            embed.add_field(
                                name=f"📌 **Task {i+1}: {task['task_name']}**  |  🏷 **Priority:** {task['priority']} {checkmark}",
                                value=f"📖 **Description:**\n{task['description']}\n"
                                    f"\n⏳ **Estimated Time:** {task['estimated_time']}\n"
                                    f"────────────",
                                inline=False
                            )

                        embed.set_footer(text=f"Completion: {completion_percentage}% ✅")
                        await webhook.edit_message(
                            message_id=message_id,
                            embed=embed
                        )

                        await interaction.response.send_message("✅ Tasks marked as complete!", ephemeral=True)

                except discord.NotFound:
                    await interaction.response.send_message("❌ Could not find the message to edit.", ephemeral=True)
                except discord.Forbidden:
                    await interaction.response.send_message("❌ Webhook lacks permission to edit the message.", ephemeral=True)
                except Exception as e:
                    await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)


class CompletionView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id

        user_tasks = list(user_tasks_daily_collection.find({"user_id": user_id, "date_today": date_today}))
        print(user_tasks)

        options = [
            discord.SelectOption(label=f"Task {i+1}: {task['task_name']}", value=str(i)+f": {task['task_name']}")
            for i, task in enumerate(user_tasks)
            if not task.get("completed", False)
        ]

        if options:
            self.add_item(CompletionSelect(user_id, options))


if __name__ == "__main__":

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        scheduler.add_job(send_daily_reminders, CronTrigger(day_of_week="0-6", hour="7", minute="30", second="0"))
        scheduler.add_job(send_daily_reminders, CronTrigger(day_of_week="0-6", hour="21", minute="00", second="0"))
        scheduler.start()

    @bot.command(guild=GUILD)
    @commands.is_owner()
    async def sync_command(ctx, guild=GUILD):
        await bot.tree.sync(guild=guild)
        await ctx.send("✅ Commands synced successfully!", delete_after = 20)

    @bot.tree.command(name="task_daily", description="Submit your daily tasks", guild=GUILD)
    async def task_daily(interaction: discord.Interaction):
        user_id = interaction.user.id
        # Redirect the user to the Flask server's form page
        form_url = f"http://localhost:5000/form?user_id={user_id}"
        await interaction.response.send_message(f"Please fill out your tasks here: {form_url}", ephemeral=True)

    @bot.tree.command(name="complete_task_daily", description="Mark completion of your daily tasks", guild=GUILD)
    async def complete_task_daily(interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.send_message("🔍 Select tasks to mark as complete.", view=CompletionView(user_id), ephemeral=True)

    bot.run(TOKEN)