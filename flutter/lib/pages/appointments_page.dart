import 'package:flutter/material.dart';
import '../api/khub_api.dart';

class AppointmentsPage extends StatefulWidget {
  _AppointmentsPageState createState() => _AppointmentsPageState();
}
class _AppointmentsPageState extends State<AppointmentsPage> {
  List _appointments = [];

  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try {
      final r = await KhubApi.get('/ops/appointments');
      setState(() => _appointments = r['appointments'] ?? []);
    } catch (_) {}
  }

  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text('预约')),
    body: ListView.builder(
      itemCount: _appointments.length,
      itemBuilder: (_, i) => ListTile(
        title: Text('${_appointments[i]['date'] ?? ''} ${_appointments[i]['doctor'] ?? ''}'),
        subtitle: Text('状态: ${_appointments[i]['status'] ?? ''}'),
      ),
    ),
  );
}
