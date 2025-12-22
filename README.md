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


MAP PARTITION

Generate WxH map with rooms => One cell handled by one "server instance"

Max number of players, must move in "lock step"

All players visible on the map. Players not seeing monsters move on their own
time.

All monsters that are close enough together form a monster group.

All players close enough to a group is part of that fight and share time

Other players can move freely but as soon as they see a monster (not player) they
join the fight

(Baldurs Gate 3)

Turn based Group:

MOVE : no  TIME : t READY: n/m

t ticks down from N seconds

When player performs action (move etc) arrow is shown and n increases

Optional: Time out (wait longer) or speed up (wait shorter) somehow voted
(Easy fight, most players want to speed things up so we do)







