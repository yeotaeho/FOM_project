import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../features/feedback/presentation/feedback_screen.dart';
import '../../features/home/presentation/home_screen.dart';
import '../../features/loading/presentation/loading_screen.dart';
import '../../features/report/presentation/report_screen.dart';
import '../../features/studio/data/compare_session.dart';
import '../../features/studio/presentation/studio_record_screen.dart';
import '../../features/studio/presentation/studio_screen.dart';
import '../theme/app_theme.dart';

CompareSession? _compareSessionFromExtra(Object? extra) {
  if (extra is CompareSession) return extra;
  if (extra is String && extra.isNotEmpty) {
    return CompareSession(
      userVideoPath: extra,
      referenceJson: '',
    );
  }
  return null;
}

final appRouter = GoRouter(
  initialLocation: '/home',
  routes: [
    ShellRoute(
      builder: (context, state, child) => _ScaffoldWithNav(child: child),
      routes: [
        GoRoute(path: '/home', builder: (ctx, st) => const HomeScreen()),
        GoRoute(path: '/studio', builder: (ctx, st) => const StudioScreen()),
        GoRoute(path: '/report', builder: (ctx, st) => const ReportScreen()),
      ],
    ),
    GoRoute(
      path: '/studio/record',
      builder: (_, _) => const StudioRecordScreen(),
    ),
    GoRoute(
      path: '/loading',
      builder: (_, state) => LoadingScreen(
        session: _compareSessionFromExtra(state.extra),
      ),
    ),
    GoRoute(
      path: '/feedback',
      builder: (_, state) {
        final session = _compareSessionFromExtra(state.extra);
        return FeedbackScreen(
          videoPath: session?.userVideoPath,
          referenceVideoPath: session?.referenceVideoPath,
        );
      },
    ),
  ],
);

class _ScaffoldWithNav extends StatelessWidget {
  final Widget child;

  const _ScaffoldWithNav({required this.child});

  int _indexFromLocation(BuildContext context) {
    final loc = GoRouterState.of(context).uri.path;
    if (loc.startsWith('/studio')) return 1;
    if (loc.startsWith('/report')) return 2;
    return 0;
  }

  @override
  Widget build(BuildContext context) {
    final idx = _indexFromLocation(context);
    return Scaffold(
      body: child,
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(
          border: Border(
            top: BorderSide(color: AppColors.divider, width: 0.5),
          ),
        ),
        child: BottomNavigationBar(
          currentIndex: idx,
          onTap: (i) {
            const paths = ['/home', '/studio', '/report'];
            context.go(paths[i]);
          },
          items: const [
            BottomNavigationBarItem(
              icon: Icon(Icons.home_rounded),
              activeIcon: Icon(Icons.home_rounded),
              label: 'Challenge',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.videocam_rounded),
              activeIcon: Icon(Icons.videocam_rounded),
              label: 'Studio',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.bar_chart_rounded),
              activeIcon: Icon(Icons.bar_chart_rounded),
              label: 'Report',
            ),
          ],
        ),
      ),
    );
  }
}
