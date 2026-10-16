function AmberLogo({ compact = false }: { compact?: boolean }) {
  return (
    <img
      className={
        compact
          ? "h-14 w-auto max-w-[170px] object-contain object-left"
          : "h-16 w-auto max-w-[205px] object-contain object-left"
      }
      src="/assets/amber-logo.svg"
      alt="Amber"
    />
  )
}

