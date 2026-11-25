import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "mint";
type Size = "sm" | "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition-[background,border-color,color,box-shadow,transform] duration-[var(--duration-base)] ease-[var(--ease-out-quint)] disabled:opacity-40 disabled:pointer-events-none active:translate-y-px";

const variants: Record<Variant, string> = {
  primary: "bg-ink-50 text-ink-950 hover:bg-white",
  mint: "bg-mint text-ink-950 hover:bg-[#8cf0c8] shadow-glow-mint",
  secondary: "border border-ink-600 bg-white/[0.03] text-ink-50 hover:border-ink-400 hover:bg-white/[0.07]",
  ghost: "text-ink-200 hover:text-ink-50 hover:bg-white/[0.06]",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3.5 text-[13px]",
  md: "h-10 px-5 text-sm",
  lg: "h-12 px-7 text-[15px]",
};

export const buttonClass = (variant: Variant = "secondary", size: Size = "md", className?: string) =>
  cn(base, variants[variant], sizes[size], className);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({ variant, size, className, type = "button", ...rest }, ref) {
  return <button ref={ref} type={type} className={buttonClass(variant, size, className)} {...rest} />;
});

type ButtonLinkProps = LinkProps & { variant?: Variant; size?: Size };

export function ButtonLink({ variant, size, className, ...rest }: ButtonLinkProps) {
  return <Link className={buttonClass(variant, size, className)} {...rest} />;
}

export function ExternalButtonLink({ variant, size, className, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: Variant; size?: Size }) {
  return <a className={buttonClass(variant, size, className)} {...rest} />;
}
