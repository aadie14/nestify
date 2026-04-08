import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';

type Props = {
  title?: string;
  defaultOpen?: boolean;
  securityReport: React.ReactNode;
  costAnalysis: React.ReactNode;
  fixPlan: React.ReactNode;
  debateLogs: React.ReactNode;
  platformBreakdown: React.ReactNode;
};

function DrawerSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="technical-drawer-section">
      <div className="technical-drawer-section-title">{title}</div>
      <div className="technical-drawer-section-body">{children}</div>
    </section>
  );
}

export default function TechnicalDetailsDrawer({
  title = 'View Technical Details',
  defaultOpen = false,
  securityReport,
  costAnalysis,
  fixPlan,
  debateLogs,
  platformBreakdown,
}: Props) {
  const [open, setOpen] = React.useState(defaultOpen);

  return (
    <section className={`technical-drawer ${open ? 'open' : ''}`}>
      <button
        type="button"
        className="technical-drawer-toggle"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span>{title}</span>
        <span className={`technical-drawer-chevron ${open ? 'open' : ''}`}>▾</span>
      </button>

      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="drawer-body"
            className="technical-drawer-body"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="technical-drawer-scroll">
              <DrawerSection title="Security report">{securityReport}</DrawerSection>
              <DrawerSection title="Cost analysis">{costAnalysis}</DrawerSection>
              <DrawerSection title="Fix plan">{fixPlan}</DrawerSection>
              <DrawerSection title="Agent debate logs (raw)">{debateLogs}</DrawerSection>
              <DrawerSection title="Platform breakdown">{platformBreakdown}</DrawerSection>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
