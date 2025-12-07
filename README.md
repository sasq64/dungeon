## DCC Inspired dungeon crawl battle royal

One `Area` is a map of room with stair cases downwards

An Area is usually controlled by one server instance

Players have a certain amount of time to find a stair case and descend.

Players can co-operate or fight

Dungeon is populated with monsters



## Eternal dungeon

Single world dungeon

Each room is an 'instance', and players in one room does not need to interact with players in other rooms

Rooms have a max active players size. If room is full, other player can phase through the room to another (open) exit

Game is tick based, but can pause if no players are moving

FEW players:

When any player moves, short timer starts, every one else have to perform their move too. Stops when everyone moved.

With no combat, no timer

Example; movement speed is 1 tile every tick (half second). If players press a direction they will move in lock step
If player lets go of button / does nothing at beginning of tick he has half the tick to do something, and will catch up
in that case


Paused / Combat

Players perform action / shown with arrow indicator before performed.
If enough players have actions, timer starts. When timer goes to zero or all players have actions, they are all perfomed


Actions

Move
Attack
Turn

Separate time in separate rooms


Straight co-op ? 






