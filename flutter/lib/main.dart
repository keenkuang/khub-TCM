import 'package:flutter/material.dart';
import 'pages/login_page.dart';
import 'pages/home_page.dart';
import 'pages/appointments_page.dart';
import 'pages/twin_page.dart';
import 'pages/trends_page.dart';
import 'pages/patients_page.dart';

void main() => runApp(KhupApp());
class KhupApp extends StatelessWidget {
  Widget build(BuildContext context) => MaterialApp(
    title: 'kHUB', theme: ThemeData(
      colorSchemeSeed: Color(0xFF4488CC), useMaterial3: true,
      brightness: Brightness.light,
    ),
    initialRoute: '/login',
    routes: {
      '/login': (_) => LoginPage(),
      '/home': (_) => HomePage(),
      '/appointments': (_) => AppointmentsPage(),
      '/twin': (_) => TwinPage(),
      '/trends': (_) => TrendsPage(),
      '/patients': (_) => PatientsPage(),
    },
  );
}
