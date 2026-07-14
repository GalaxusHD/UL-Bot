"""
Admin role permission checking utilities.
Provides role-based access control for commands.
"""

import sqlite3
from database import DB_FILE


def has_admin_role(guild_id: int, user_id: int, user_roles: list[int]) -> bool:
    """
    Check if user has an admin role configured for the guild.
    
    Args:
        guild_id: Discord guild ID
        user_id: Discord user ID
        user_roles: List of role IDs the user has
    
    Returns:
        True if user has an admin role or Discord admin permission, False otherwise
    """
    if not user_roles:
        return False
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            # Check if any of the user's roles are registered as admin roles
            placeholders = ','.join('?' * len(user_roles))
            query = f'''
                SELECT 1
                FROM admin_roles
                WHERE guild_id = ? AND role_id IN ({placeholders})
                LIMIT 1
            '''
            row = conn.execute(query, (guild_id, *user_roles)).fetchone()
            return row is not None
    except Exception as e:
        print(f'❌ Error checking admin role: {e}')
        return False


def add_admin_role(guild_id: int, role_id: int) -> bool:
    """Add an admin role for the guild."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                'INSERT OR IGNORE INTO admin_roles (guild_id, role_id) VALUES (?, ?)',
                (guild_id, role_id),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f'❌ Error adding admin role: {e}')
        return False


def remove_admin_role(guild_id: int, role_id: int) -> bool:
    """Remove an admin role for the guild."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                'DELETE FROM admin_roles WHERE guild_id = ? AND role_id = ?',
                (guild_id, role_id),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f'❌ Error removing admin role: {e}')
        return False


def get_admin_roles(guild_id: int) -> list[int]:
    """Get all admin role IDs for a guild."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute(
                'SELECT role_id FROM admin_roles WHERE guild_id = ? ORDER BY role_id',
                (guild_id,),
            ).fetchall()
        return [int(row[0]) for row in rows]
    except Exception as e:
        print(f'❌ Error getting admin roles: {e}')
        return []
