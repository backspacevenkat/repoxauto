import React from 'react';
import { useRouter } from 'next/router';
import {
  Box,
  Drawer,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Typography,
  useTheme,
  Divider
} from '@mui/material';
import {
  People as PeopleIcon,
  Task as TaskIcon,
  Settings as SettingsIcon,
  Dashboard as DashboardIcon,
  Search as SearchIcon,
  PlayArrow as ActionsIcon,
  Person as ProfileIcon,
  PersonAdd as FollowIcon,
  Key as KeyIcon,
  Help as HelpIcon
} from '@mui/icons-material';

const DRAWER_WIDTH = 240;

const menuItems = [
  { text: 'Dashboard', icon: <DashboardIcon />, path: '/' },
  { text: 'Accounts', icon: <PeopleIcon />, path: '/accounts' },
  { text: 'Act Setup', icon: <KeyIcon />, path: '/act-setup' },
  { text: 'Tasks', icon: <TaskIcon />, path: '/tasks' },
  { text: 'Search', icon: <SearchIcon />, path: '/search' },
  { text: 'Actions', icon: <ActionsIcon />, path: '/actions' },
  { text: 'Profile Updates', icon: <ProfileIcon />, path: '/profile-updates' },
  { text: 'Follow System', icon: <FollowIcon />, path: '/follow' },
  { text: 'Settings', icon: <SettingsIcon />, path: '/settings' },
  { text: 'Help', icon: <HelpIcon />, path: '/help' }
];

export default function Layout({ children }) {
  const router = useRouter();
  const theme = useTheme();

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            boxSizing: 'border-box',
            backgroundColor: theme.palette.background.default,
            borderRight: `1px solid ${theme.palette.divider}`
          },
        }}
      >
        <Box sx={{ p: 2 }}>
          <Typography variant="h6" component="div" sx={{ fontWeight: 'bold' }}>
            Xauto
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Twitter Management
          </Typography>
        </Box>
        <Divider />
        <List>
          {menuItems.map((item) => (
            <ListItem
              button
              key={item.text}
              onClick={() => router.push(item.path)}
              selected={router.pathname === item.path}
              sx={{
                '&.Mui-selected': {
                  backgroundColor: theme.palette.action.selected,
                  '&:hover': {
                    backgroundColor: theme.palette.action.hover,
                  },
                },
                '&:hover': {
                  backgroundColor: theme.palette.action.hover,
                },
                borderRadius: 1,
                mx: 1,
                my: 0.5,
              }}
            >
              <ListItemIcon sx={{ 
                minWidth: 40,
                color: router.pathname === item.path ? 
                  theme.palette.primary.main : 
                  theme.palette.text.secondary 
              }}>
                {item.icon}
              </ListItemIcon>
              <ListItemText 
                primary={item.text} 
                sx={{
                  '& .MuiListItemText-primary': {
                    color: router.pathname === item.path ? 
                      theme.palette.primary.main : 
                      theme.palette.text.primary,
                    fontWeight: router.pathname === item.path ? 
                      'bold' : 
                      'normal'
                  }
                }}
              />
            </ListItem>
          ))}
        </List>
      </Drawer>
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          backgroundColor: theme.palette.background.default,
          minHeight: '100vh'
        }}
      >
        {children}
      </Box>
    </Box>
  );
}
