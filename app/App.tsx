import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { StatusBar } from 'expo-status-bar';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import {
  SafeAreaProvider, SafeAreaView, useSafeAreaInsets,
} from 'react-native-safe-area-context';

import { setAuthFailHandler } from './src/api';
import { loadSession } from './src/auth';
import { TabIcon } from './src/components/icons';
import AdventureDetail from './src/screens/AdventureDetail';
import AdventureForm from './src/screens/AdventureForm';
import Adventures from './src/screens/Adventures';
import GearDetail from './src/screens/GearDetail';
import GearForm from './src/screens/GearForm';
import GearLocker from './src/screens/GearLocker';
import Home from './src/screens/Home';
import Login from './src/screens/Login';
import Pack from './src/screens/Pack';
import { Discover } from './src/screens/Placeholders';
import Profile from './src/screens/Profile';
import { S, T, TAP, useTheme } from './src/theme';

/**
 * SHAPE
 *
 *   Root (stack)
 *     ├─ Login              — when signed out. Never in the stack beside Tabs.
 *     ├─ Tabs               — Home · Adventures · Gear · Discover · Profile
 *     ├─ AdventureDetail · AdventureForm · Pack
 *     └─ GearDetail · GearForm
 *
 * Detail screens and forms push on the ROOT stack rather than inside their tab,
 * so the tab bar is not present while editing. A form with a tab bar under it
 * offers two contradictory ways out of an unsaved change.
 *
 * Both details are reachable from two tabs — Home links to the next adventure
 * and to recent gear — which is the other reason they live on the root rather
 * than inside one tab's stack: a screen owned by a tab can only be pushed from
 * that tab.
 *
 * Auth screens and app screens are never both mounted. Signing out therefore
 * cannot leave a locker screen underneath a login form, which a navigate()
 * would.
 */
const Root = createNativeStackNavigator();
const Tabs = createBottomTabNavigator();

/** The bar is sized to the glove-usable minimum rather than to the platform
 *  default, so the tap target is stated by the same constant every other
 *  control in the app reads. */
const TAB_H = TAP;

function TabsScreen({ navigation }: any) {
  const { P } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <Tabs.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: P.brand,
        tabBarInactiveTintColor: P.textMuted,
        tabBarStyle: {
          backgroundColor: P.card,
          borderTopColor: P.hairline,
          height: TAB_H + insets.bottom,
          paddingTop: 6,
          paddingBottom: insets.bottom,
        },
        tabBarLabelStyle: { ...T.caption, fontSize: 11, marginTop: 1 },
        tabBarIcon: ({ color }) => (
          <TabIcon
            size={22}
            color={color}
            kind={route.name === 'Home' ? 'home'
              : route.name === 'Adventures' ? 'adventures'
              : route.name === 'Gear' ? 'gear'
              : route.name === 'Discover' ? 'discover' : 'profile'}
          />
        ),
      })}>
      <Tabs.Screen name="Home">
        {() => (
          <Home
            onOpenGear={(id: string) => navigation.navigate('GearDetail', { id })}
            onAddGear={() => navigation.navigate('GearForm', {})}
            // Addressed THROUGH the tab navigator, not as a sibling route.
            // `navigation` here belongs to the root stack, which has no route
            // called 'Gear' — that name only exists inside Tabs. Calling it
            // directly threw a NAVIGATE error and left the button dead.
            onGearTab={() => navigation.navigate('Tabs', { screen: 'Gear' })}
            onOpenAdventure={(id: string) => navigation.navigate('AdventureDetail', { id })}
            onPlanAdventure={() => navigation.navigate('AdventureForm', {})}
          />
        )}
      </Tabs.Screen>

      <Tabs.Screen name="Adventures">
        {() => (
          <Adventures
            onOpen={(id: string) => navigation.navigate('AdventureDetail', { id })}
            onCreate={() => navigation.navigate('AdventureForm', {})}
          />
        )}
      </Tabs.Screen>

      <Tabs.Screen name="Gear">
        {() => (
          <GearLocker
            onOpen={(id: string) => navigation.navigate('GearDetail', { id })}
            onAdd={() => navigation.navigate('GearForm', {})}
          />
        )}
      </Tabs.Screen>

      <Tabs.Screen name="Discover" component={Discover} />

      <Tabs.Screen name="Profile">
        {() => <Profile onSignedOut={() => navigation.getParent()?.navigate('SignedOut')} />}
      </Tabs.Screen>
    </Tabs.Navigator>
  );
}

function Boot() {
  const { P } = useTheme();
  return (
    <View style={{ flex: 1, backgroundColor: P.pageBg,
                   alignItems: 'center', justifyContent: 'center', gap: S[4] }}>
      <Text style={[T.display, { color: P.textPri }]}>Voyage Outdoor</Text>
      <ActivityIndicator color={P.brand} />
    </View>
  );
}

export default function App() {
  const { mode, P } = useTheme();
  const [booting, setBooting] = useState(true);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    // A 401 that survives one refresh means the session is gone. Handled here
    // rather than per-screen so every request in the app has the same answer.
    setAuthFailHandler(() => setAuthed(false));
    (async () => {
      const state = await loadSession();
      setAuthed(state === 'authed');
      setBooting(false);
    })();
  }, []);

  if (booting) {
    return (
      <SafeAreaProvider>
        <Boot />
      </SafeAreaProvider>
    );
  }

  return (
    <SafeAreaProvider>
      {/* The status bar follows the palette rather than being pinned. Pinned
          dark-content on a dark page is an invisible clock. */}
      <StatusBar style={mode === 'dark' ? 'light' : 'dark'} />
      <SafeAreaView style={{ flex: 1, backgroundColor: P.pageBg }} edges={['top']}>
        <NavigationContainer
          theme={{
            dark: mode === 'dark',
            colors: {
              primary: P.brand, background: P.pageBg, card: P.card,
              text: P.textPri, border: P.hairline, notification: P.brand,
            },
            fonts: {
              regular: { fontFamily: 'System', fontWeight: '400' },
              medium: { fontFamily: 'System', fontWeight: '500' },
              bold: { fontFamily: 'System', fontWeight: '700' },
              heavy: { fontFamily: 'System', fontWeight: '700' },
            },
          }}>
          <Root.Navigator screenOptions={{ headerShown: false }}>
            {!authed ? (
              <Root.Screen name="Login">
                {() => <Login onDone={() => setAuthed(true)} />}
              </Root.Screen>
            ) : (
              <>
                <Root.Screen name="Tabs" component={TabsScreen} />

                {/* Profile's sign-out routes here rather than calling a
                    setter through three layers of navigator props. */}
                <Root.Screen name="SignedOut">
                  {() => { setAuthed(false); return null; }}
                </Root.Screen>

                <Root.Screen name="AdventureDetail"
                             options={{ headerShown: true, title: '' }}>
                  {({ navigation, route }: any) => (
                    <AdventureDetail
                      adventureId={route.params.id}
                      onEdit={() => navigation.navigate('AdventureForm', { id: route.params.id })}
                      onPack={(title: string) =>
                        navigation.navigate('Pack', { id: route.params.id, title })}
                      onGone={() => navigation.goBack()}
                    />
                  )}
                </Root.Screen>

                <Root.Screen name="AdventureForm"
                             options={{ headerShown: true, title: '' }}>
                  {({ navigation, route }: any) => (
                    <AdventureForm
                      adventureId={route.params?.id}
                      onDone={(id: string) => {
                        if (route.params?.id) navigation.goBack();
                        else navigation.replace('AdventureDetail', { id });
                      }}
                      onCancel={() => navigation.goBack()}
                    />
                  )}
                </Root.Screen>

                <Root.Screen name="Pack"
                             options={{ headerShown: true, title: '' }}>
                  {({ navigation, route }: any) => (
                    <Pack adventureId={route.params.id} title={route.params.title}
                          onBack={() => navigation.goBack()} />
                  )}
                </Root.Screen>

                <Root.Screen name="GearDetail"
                             options={{ headerShown: true, title: '' }}>
                  {({ navigation, route }: any) => (
                    <GearDetail
                      gearId={route.params.id}
                      onEdit={() => navigation.navigate('GearForm', { id: route.params.id })}
                      onGone={() => navigation.goBack()}
                    />
                  )}
                </Root.Screen>

                <Root.Screen name="GearForm"
                             options={{ headerShown: true, title: '' }}>
                  {({ navigation, route }: any) => (
                    <GearForm
                      gearId={route.params?.id}
                      onDone={(id: string) => {
                        // replace, not push: coming back from a saved form
                        // should land on the item, never on the form again.
                        if (route.params?.id) navigation.goBack();
                        else navigation.replace('GearDetail', { id });
                      }}
                      onCancel={() => navigation.goBack()}
                    />
                  )}
                </Root.Screen>
              </>
            )}
          </Root.Navigator>
        </NavigationContainer>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}
